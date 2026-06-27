import onnxruntime as ort
import logging
MODEL_PATH = 'PUBGV8S_640.onnx'

logger = logging.getLogger(__name__)

# 只用CUDA，跳过TensorRT
providers = [
    ('CUDAExecutionProvider', {
        'device_id': 0,
        'arena_extend_strategy': 'kNextPowerOfTwo',
        'cudnn_conv_algo_search': 'EXHAUSTIVE',
    }),
    'CPUExecutionProvider',  # 保底
]

try:
    session = ort.InferenceSession(MODEL_PATH, providers=providers)
    actual_provider = session.get_providers()[0]
    logger.info(f"✅ 使用推理后端: {actual_provider}")
    logger.info(f"ONNX Runtime 设备: {ort.get_device()}")
except Exception as e:
    logger.error(f"CUDA初始化失败: {e}")
    # 降级到CPU
    session = ort.InferenceSession(MODEL_PATH, providers=['CPUExecutionProvider'])
    logger.warning("⚠️ 降级到CPU推理")