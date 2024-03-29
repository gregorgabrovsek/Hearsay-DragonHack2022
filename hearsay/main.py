import uuid

import uvicorn
from fastapi import Depends, File, UploadFile, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import time
import random

import tempfile
from starlette.responses import FileResponse
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from hearsay.av_management.video_mgmt import extract_audio_from_mp4
from hearsay.assembly.manager import upload_audio_to_assembly, submit_for_transcription, get_transcription_result
from hearsay.subtitles.srtGen import srt_from_transcription, write_to_file, srt_from_transcription_and_srt, \
    srt_from_transcription_and_text
from hearsay.subtitles.vtt import convert_file_to_vtt
from hearsay.cloud_translation.google import translate_text

temp = tempfile.TemporaryDirectory(prefix="hearsay_")
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def file_location():
    return temp.name


app.mount("/web_page", StaticFiles(directory="web_page"), name="static")


@app.post("/upload")
async def upload_video(path: str = Depends(file_location), file: UploadFile = File(...)):
    full_name = os.path.join(path, file.filename)
    if not file.filename.endswith(".mp4"):
        return {"message": "File must be an MP4 file."}
    try:
        contents = await file.read()
        with open(full_name, 'wb+') as f:
            f.write(contents)
    except Exception as e:
        return {"message": "There was an error uploading the file"}
    finally:
        await file.close()

    return {"message": "Success", "file_name": file.filename}


@app.get("/translation/{file_name}", response_class=PlainTextResponse)
async def download_video(file_name: str, path: str = Depends(file_location)):
    with open(os.path.join(path, file_name), "r") as f:
        return translate_text(text=f.read())


@app.get("/uploaded/{file_name}", response_class=FileResponse)
async def download_video(file_name: str, path: str = Depends(file_location)):
    full_name = os.path.join(path, file_name)
    return full_name


@app.get("/subtitle/{file_name}", response_class=PlainTextResponse)
async def subtitle(
    file_name: str,
    path: str = Depends(file_location),
):
    with open(os.path.join(path, file_name), "r") as f:
        return f.read()


@app.post("/transcribe/{file_name}")
async def transcribe(
        file_name: str,
        script: str | None = None,
        path: str = Depends(file_location),
        subtitle_file: UploadFile | None = File(None)
):
    audio_location = extract_audio_from_mp4(video_name=file_name, temporary_folder_location=path)
    upload_result = upload_audio_to_assembly(audio_path=os.path.join(path, audio_location))
    upload_id = submit_for_transcription(audio_url=upload_result.upload_url)
    i = 0
    while True:
        try:
            transcription_result = get_transcription_result(job_id=upload_id.id)
            if transcription_result.status in ["completed", "error"]:
                break
        except:
            pass

        time.sleep(2 ** i)
        i += 1

    if (script is None or not script) and subtitle_file is None:
        generated_srt = srt_from_transcription(transcription=transcription_result)

    elif subtitle_file is None:
        generated_srt = srt_from_transcription_and_text(
            transcription=transcription_result,
            real_text=script,
        )

    else:
        generated_srt = srt_from_transcription_and_text(
            transcription=transcription_result,
            real_text=script,
        )
    
    subtitle_name = f"{str(uuid.uuid4())}.srt"
    full_subtitle_name = os.path.join(path, subtitle_name)
    write_to_file(full_subtitle_name, generated_srt)
    convert_file_to_vtt(full_subtitle_name)
    return {"subtitle_name": subtitle_name.replace(".srt", ".vtt")}


if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)
