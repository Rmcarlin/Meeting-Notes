import unittest
from unittest.mock import Mock, patch

from speech_recognition import load_model


class RecognitionBackendTests(unittest.TestCase):
    @patch("faster_whisper.utils.download_model", return_value="cached-large-v3-turbo")
    def test_same_model_runs_on_cpu_when_gpu_libraries_are_unavailable(self, resolve):
        with patch("speech_recognition.gpu_available", return_value=False), \
                patch("faster_whisper.WhisperModel") as factory:
            model = load_model("large-v3-turbo", Mock())
        self.assertIs(model, factory.return_value)
        self.assertEqual(factory.call_args.args, ("cached-large-v3-turbo",))
        self.assertEqual(factory.call_args.kwargs["device"], "cpu")
        self.assertTrue(resolve.call_args.kwargs["local_files_only"])

    @patch("faster_whisper.utils.download_model", return_value="cached-large-v3-turbo")
    def test_gpu_load_failure_retries_on_cpu(self, resolve):
        fallback = Mock()
        with patch("speech_recognition.gpu_available", return_value=True), \
                patch("faster_whisper.WhisperModel", side_effect=[RuntimeError("CUDA unavailable"), fallback]) as factory:
            model = load_model("large-v3-turbo", Mock())
        self.assertIs(model, fallback)
        self.assertEqual([call.kwargs["device"] for call in factory.call_args_list], ["cuda", "cpu"])

    def test_first_use_can_download_an_uncached_model(self):
        with patch("faster_whisper.utils.download_model", side_effect=FileNotFoundError), \
                patch("speech_recognition.gpu_available", return_value=False), \
                patch("faster_whisper.WhisperModel") as factory:
            load_model("large-v3-turbo", Mock())
        self.assertEqual(factory.call_args.args, ("large-v3-turbo",))
