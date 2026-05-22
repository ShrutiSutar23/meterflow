# ==========================================
# LINES 1-6: THIS MUST BE AT THE VERY TOP
# ==========================================
import os
import sys

# Forces Vercel's environment to see the root workspace modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ==========================================
# REST OF YOUR IMPORTS (Starting around line 7+)
# ==========================================
# ... your other third-party imports (like fastapi, uvicorn, etc.) ...

# This will now successfully look inside the root backend folder
from backend.config.database import connect_db, disconnect_db