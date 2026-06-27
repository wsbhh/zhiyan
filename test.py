import onnxruntime as ort
import logging
MODEL_PATH = 'PUBGV8S_640.onnx'
# ========== 日志配置 ==========
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/app.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()
# 更稳健的GPU检测
def get_available_providers():
    """获取系统可用的推理后端"""
    available = []

    # 检查CUDA
    try:
        if 'CUDAExecutionProvider' in ort.get_available_providers():
            available.append(('CUDAExecutionProvider', {'device_id': 0}))
    except:
        pass

    # 检查DirectML (仅Windows)
    try:
        import platform
        if platform.system() == 'Windows' and 'DmlExecutionProvider' in ort.get_available_providers():
            available.append('DmlExecutionProvider')
    except:
        pass

    # CPU保底
    available.append('CPUExecutionProvider')
    return available


# 使用
providers = get_available_providers()
session = ort.InferenceSession(MODEL_PATH, providers=providers)
actual_provider = session.get_providers()[0]

if 'CUDA' in actual_provider:
    logger.info("✅ 使用 NVIDIA GPU (CUDA) 加速")
elif 'Dml' in actual_provider:
    logger.info("✅ 使用 DirectML (GPU) 加速")
else:
    logger.warning("⚠️ 使用 CPU 推理，性能可能较慢")