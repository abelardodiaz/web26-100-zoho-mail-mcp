import sys
from pathlib import Path

# El servidor vive en src/; las pruebas lo importan desde ahi.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
