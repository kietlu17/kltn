import unittest
import subprocess
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from src.api.speech import MAX_BYTES, router, transcribe_audio, _lock


class SpeechTests(unittest.TestCase):
    def test_silence_and_duration_limits_before_model_load(self):
        import numpy as np
        for seconds, expected in [(0, 400), (0.5, 400), (2, None), (61, 400)]:
            audio = np.zeros(int(seconds * 16000), dtype=np.float32).tobytes()
            with patch('src.api.speech.subprocess.run', return_value=subprocess.CompletedProcess([], 0, audio, b'')):
                if expected:
                    with self.assertRaises(HTTPException) as error:
                        transcribe_audio(b'audio')
                    self.assertEqual(error.exception.status_code, expected)
                else:
                    self.assertEqual(transcribe_audio(b'audio'), '')
            self.assertFalse(_lock.locked())

    def test_audio_validation_and_transcript(self):
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client, patch('src.api.speech.transcribe_audio', return_value='Tìm tai nghe') as model:
            self.assertEqual(client.post('/assistant/transcribe', content=b'abc', headers={'Content-Type':'text/plain'}).status_code, 415)
            self.assertEqual(client.post('/assistant/transcribe', content=b'', headers={'Content-Type':'audio/webm'}).status_code, 400)
            self.assertEqual(client.post('/assistant/transcribe', content=b'a'*(MAX_BYTES+1), headers={'Content-Type':'audio/webm'}).status_code, 413)
            model.assert_not_called()
            result = client.post('/assistant/transcribe', content=b'audio', headers={'Content-Type':'audio/webm;codecs=opus'})
            self.assertEqual(result.json(), {'text':'Tìm tai nghe'})
            model.assert_called_once_with(b'audio')

    def test_busy_inference_rejected(self):
        _lock.acquire()
        try:
            with self.assertRaises(HTTPException) as error:
                transcribe_audio(b'audio')
            self.assertEqual(error.exception.status_code, 429)
        finally:
            _lock.release()

    def test_decoder_rejects_bad_audio_and_releases_lock(self):
        with self.assertRaises(HTTPException) as error:
            transcribe_audio(b'not audio')
        self.assertEqual(error.exception.status_code, 400)
        self.assertFalse(_lock.locked())
