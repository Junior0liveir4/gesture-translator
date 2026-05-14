import json
import time
import numpy as np
import os
import socket
from is_wire.core import Subscription, Message
from streamChannel import StreamChannel

# --- Configuração ---
broker_uri = "amqp://guest:guest@10.10.2.211:30000"
topic_gesture = "GestureDetector.1.Detection"
topic_skeleton = "SkeletonDetector.3D.Annotations"
topic_result = "Action.Result"
LOG_FILE = "historico.json"
MAX_COLLECTIONS = 5
TIMEOUT_COLLECTION = 10.0 

def extract_coords(skeleton):
    """Extrai as coordenadas 3D dos keypoints 6 (Ombro), 8 (Cotovelo) e 10 (Pulso)."""
    coords = {}
    skeleton_3d = skeleton.get("skeleton_3d", {})
    coords["keypoint_6"] = skeleton_3d.get("7")
    coords["keypoint_8"] = skeleton_3d.get("9")
    coords["keypoint_10"] = skeleton_3d.get("11")
    return coords

def calculate_average_point(data, keypoint_name):
    """Cálculo do ponto 3D médio da lista de dados coletados."""
    sum_x, sum_y, sum_z = 0.0, 0.0, 0.0
    valid_points_count = 0

    for entry in data:
        coords = entry.get(keypoint_name)
        if coords:
            sum_x += coords[0]
            sum_y += coords[1]
            sum_z += coords[2]
            valid_points_count += 1

    if valid_points_count == 0:
        return None

    avg_x = sum_x / valid_points_count
    avg_y = sum_y / valid_points_count
    avg_z = sum_z / valid_points_count
    return [avg_x, avg_y, avg_z]

def compare_gestures(g1, g2):
    if g1 is None or g2 is None:
        return False
    return (g1.get("id") == g2.get("id") and
            g1.get("camera_key") == g2.get("camera_key") and
            g1.get("gesture") == g2.get("gesture"))

def calculate_median_point(data, keypoint_name):
    """
    Usa a MEDIANA.
    Isso ignora valores extremos (outliers) se o sensor falhar em 1 ou 2 frames.
    """
    x_list, y_list, z_list = [], [], []

    for entry in data:
        coords = entry.get(keypoint_name)
        if coords:
            x_list.append(coords[0])
            y_list.append(coords[1])
            z_list.append(coords[2])

    if not x_list:
        return None

    # Retorna a mediana de cada eixo
    return [np.median(x_list), np.median(y_list), np.median(z_list)]

def calculate_ground_projection(points_3d):
    """
    Calcula a projeção usando o vetor OMBRO -> PULSO.
    """
    # Verifica se temos Ombro e Pulso (Cotovelo opcional para a reta)
    if "Right Shoulder" not in points_3d or "Right Wrist" not in points_3d:
        print("[ERRO] Ombro ou Pulso ausentes para cálculo do vetor longo.")
        return None

    p_origem = points_3d["Right Shoulder"] # Origem = Ombro (Keypoint 6)
    p_fim = points_3d["Right Wrist"]       # Fim = Pulso (Keypoint 10)
    
    vetor_direcao = p_fim - p_origem
    
    z_origem = p_origem[2, 0]
    z_direcao = vetor_direcao[2, 0]
    
    # Evita divisão por zero se braço estiver perfeitamente paralelo ao chão
    if abs(z_direcao) < 1e-6:
        return None
        
    # Equação da reta: P_chao = P_origem + t * Vetor
    # Z=0 => 0 = z_origem + t * z_direcao => t = -z_origem / z_direcao
    t = -z_origem / z_direcao
    
    ponto_no_chao = p_origem + t * vetor_direcao
    
    print(f"🎯 Projeção (Vetor Ombro-Pulso): (X: {ponto_no_chao[0, 0]:.2f}, Y: {ponto_no_chao[1, 0]:.2f})")
    return ponto_no_chao

def handle_stop_gesture(gesture_info, channel):
    print(f"\n>>> GESTO 'STOP' RECEBIDO: {gesture_info} <<<")
    msg = Message()
    msg.body = json.dumps({"stop": 0}).encode('utf-8')
    msg.topic = topic_result
    try:
        channel.publish(msg)
    except Exception as e:
        print(f"Erro pub stop: {e}")

def end_collection(data, reason, collection_start_time, channel):
    print(f"\n=== COLETA ENCERRADA ({reason}) ===")
    ground_projection_point = None 
    
    if data:
        print(f"Dados utilizados para Mediana: {len(data)} amostras.")
        
        # Calcular a MEDIANA do Ombro (6) e do Pulso (10)
        median_shoulder = calculate_median_point(data, "keypoint_6")
        median_wrist = calculate_median_point(data, "keypoint_10")

        if median_shoulder and median_wrist:
            points_3d = {
                "Right Shoulder": np.array(median_shoulder).reshape(3, 1),
                "Right Wrist": np.array(median_wrist).reshape(3, 1)
            }
            ground_projection_point = calculate_ground_projection(points_3d)
        else:
            print("[AVISO] Faltam dados do Ombro ou Pulso para projeção.")

    if reason != "Gesto 'stop' recebido" and ground_projection_point is not None:
        payload = {"move": [round(ground_projection_point[0, 0], 2), round(ground_projection_point[1, 0], 2)]}
        print(f"--- ENVIANDO 'MOVE': {payload} ---")
        msg = Message(content=json.dumps(payload).encode('utf-8'))
        msg.topic = topic_result
        try:
            channel.publish(msg)
        except Exception as e:
            print(f"Erro pub move: {e}")
    
    if collection_start_time:
        tempo_total = time.perf_counter() - collection_start_time
        print(f"[TEMPO TOTAL]: {time.perf_counter() - collection_start_time:.4f}s")
        x_val = ground_projection_point[0, 0]
        y_val = ground_projection_point[1, 0]
        salvar_json(x_val, y_val, tempo_total)
    print("-------------------------\n")
    
    # Retorna estado resetado
    return False, [], 0, None, 0

def salvar_json(x, y, duration):
    novo = {
        "X": round(x, 4),
        "Y": round(y, 4),
        "tempo": round(duration, 4)
    }

    dados_existentes = []

    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE)   > 0:
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                dados_existentes = json.load(f)
        except json.JSONDecodeError:
            print("Criando novo arquivo.")
            dados_existentes = []

    if not isinstance(dados_existentes, list):
        dados_existentes = []

    dados_existentes.append(novo)

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(dados_existentes, f, indent=4, ensure_ascii=False)
        print("Dados salvos.")
    except Exception as e:
        print("Erro al salvar.")

# --- Conexão ---
try:
    channel_gesture = StreamChannel(broker_uri)
    sub_gesture = Subscription(channel=channel_gesture)
    sub_gesture.subscribe(topic=topic_gesture)
    
    channel_skeleton = StreamChannel(broker_uri)
    sub_skeleton = Subscription(channel=channel_skeleton)
    sub_skeleton.subscribe(topic=topic_skeleton)
    print(f"Conectado. Max Collections: {MAX_COLLECTIONS}")
except Exception as e:
    print(f"Erro conexão: {e}")
    exit(1)

# --- Variáveis de Estado ---
has_received_gesture = False
latest_gesture_info = None
is_collecting = False
collection_data = []
collection_count = 0
max_cameras_seen = 0 
triggering_gesture_info = None
collection_start_time = None 

while True:
    try:
        if is_collecting:
            if collection_start_time and (time.perf_counter() - collection_start_time > TIMEOUT_COLLECTION):
                 is_collecting, collection_data, collection_count, triggering_gesture_info, max_cameras_seen = \
                    end_collection(collection_data, "Timeout", collection_start_time, channel_gesture)
                 continue

            # 1. Checa Gesto
            try:
                msg_gest = channel_gesture.consume(timeout=0.1)
                data = json.loads(msg_gest.body.decode('utf-8'))
                curr_info = {"gesture": data.get("gesture"), "id": data.get("id"), "camera_key": str(data.get("camera"))}

                if curr_info.get("gesture") == "stop":
                    handle_stop_gesture(curr_info, channel_gesture)
                    is_collecting, collection_data, collection_count, triggering_gesture_info, max_cameras_seen = \
                        end_collection(collection_data, "Stop recebido", collection_start_time, channel_gesture)
                    latest_gesture_info = curr_info 
                    continue

                if not compare_gestures(triggering_gesture_info, curr_info):
                    is_collecting, collection_data, collection_count, triggering_gesture_info, max_cameras_seen = \
                        end_collection(collection_data, "Gesto mudou", collection_start_time, channel_gesture)
                    latest_gesture_info = curr_info
                    continue
            except Exception:
                pass

            # 2. Checa Esqueleto
            try:
                msg_skel = channel_skeleton.consume(timeout=0.1)
                skeleton_list = json.loads(msg_skel.body.decode('utf-8'))
                
                target_id = triggering_gesture_info["id"]
                target_cam = str(int(triggering_gesture_info["camera_key"]) - 1)

                current_skeleton = None
                current_cam_count = 0

                for skeleton in skeleton_list:
                    matche_2d = skeleton.get("matche_2d", {})
                    if target_cam in matche_2d and matche_2d[target_cam] == target_id:
                        count = len(matche_2d)
                        if count > current_cam_count:
                            current_cam_count = count
                            current_skeleton = skeleton
                
                if current_skeleton:
                    # Lógica de Upgrade de Qualidade (Prioriza maior qtde de câmeras para reconstrução)
                    if current_cam_count > max_cameras_seen:
                        print(f"    -> [UPGRADE] Qualidade subiu ({max_cameras_seen} -> {current_cam_count} câmeras). Reiniciando coleta.")
                        collection_data = [] 
                        collection_count = 0 
                        max_cameras_seen = current_cam_count 
                        
                        coords = extract_coords(current_skeleton)
                        collection_data.append(coords)
                        collection_count += 1
                        print(f"    -> Frame 1/{MAX_COLLECTIONS} (Qualidade: {max_cameras_seen} cams)")

                    elif current_cam_count == max_cameras_seen:
                        collection_count += 1
                        coords = extract_coords(current_skeleton)
                        collection_data.append(coords)
                        print(f"    -> Frame {collection_count}/{MAX_COLLECTIONS} (Qualidade: {max_cameras_seen} cams)")
                    
                    else:
                        print(f"    -> [IGNORADO] Frame inferior ({current_cam_count} < {max_cameras_seen} câmeras).")

            except Exception as e:
                if "timed out" not in str(e):
                    print(f"Erro esqueleto: {e}")

            if collection_count >= MAX_COLLECTIONS:
                is_collecting, collection_data, collection_count, triggering_gesture_info, max_cameras_seen = \
                    end_collection(collection_data, "Limite atingido", collection_start_time, channel_gesture)

        else:
            # Modo Ocioso
            try:
                msg_gest = channel_gesture.consume(timeout=0.1)
                has_received_gesture = True
                data = json.loads(msg_gest.body.decode('utf-8'))
                latest_gesture_info = {"gesture": data.get("gesture"), "id": data.get("id"), "camera_key": str(data.get("camera"))}
                
                if latest_gesture_info.get("gesture") == "stop":
                    handle_stop_gesture(latest_gesture_info, channel_gesture)

            except Exception:
                pass

            try:
                msg_skel = channel_skeleton.consume(timeout=0.1)
                
                if has_received_gesture and latest_gesture_info and latest_gesture_info.get("gesture") == "move":
                    skeleton_list = json.loads(msg_skel.body.decode('utf-8'))
                    target_id = latest_gesture_info["id"]
                    target_cam = str(int(latest_gesture_info["camera_key"]) - 1)

                    best_skel = None
                    best_count = 0

                    for skeleton in skeleton_list:
                        matche_2d = skeleton.get("matche_2d", {})
                        if target_cam in matche_2d and matche_2d[target_cam] == target_id:
                            count = len(matche_2d)
                            if count > best_count:
                                best_count = count
                                best_skel = skeleton
                    
                    if best_skel:
                        print(f"\n[START] MATCH INICIAL ({best_count} câmeras)! Iniciando coleta.")
                        
                        collection_start_time = time.perf_counter()
                        is_collecting = True
                        collection_data = []
                        collection_count = 1
                        max_cameras_seen = best_count 
                        triggering_gesture_info = latest_gesture_info.copy()
                        
                        collection_data.append(extract_coords(best_skel))

            except Exception:
                pass

    except KeyboardInterrupt:
        break
    except Exception as e:
        time.sleep(1)

if 'channel_gesture' in locals(): channel_gesture.close()
if 'channel_skeleton' in locals(): channel_skeleton.close()