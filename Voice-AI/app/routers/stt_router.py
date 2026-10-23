from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from app.auth import get_current_user
import shutil
import os

# Replace with local Whisper STT function (transcribe_audio_file_local)
from app.services.stt_service import transcribe_audio_file_local, convert_webm_to_wav

router = APIRouter()



UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/")
async def stt(
    current_user: dict = Depends(get_current_user),
    audio: UploadFile = File(...)):
    webm_path = os.path.join(UPLOAD_DIR, audio.filename)

    with open(webm_path, "wb") as buffer:
        shutil.copyfileobj(audio.file, buffer)

    try:
        # Convert webm → wav
        wav_path = webm_path.replace(".webm", ".wav")
        convert_webm_to_wav(webm_path, wav_path)

        # Whisper STT (using local version)
        text = transcribe_audio_file_local(wav_path)

        os.remove(webm_path)
        os.remove(wav_path)
        return {
            "text": text,
            "user": current_user  # For debugging: verify user information
        }
    except Exception as e:
        return {"error": str(e)}
