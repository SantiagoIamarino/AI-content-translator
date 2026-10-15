"""Offline comparison-tool regression: preserve the displayed seek origin."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from aidub.util import write_json

spec=importlib.util.spec_from_file_location("performance_evaluate",Path(__file__).resolve().parents[1]/"scripts/performance-evaluate.py")
evaluation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"ffmpeg/ffprobe unavailable")
class PictureOriginTests(unittest.TestCase):
    def test_comparison_uses_source_frame_instead_of_normalized_keyframe_preroll(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);baseline=root/"baseline";baseline.mkdir();out=root/"comparison";out.mkdir()
            source=root/"source.mp4"
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","testsrc=size=64x64:rate=10",
                            "-t","3","-c:v","libx264","-g","10","-pix_fmt","yuv420p",str(source)],check=True)
            write_json(baseline/"manifest.json",{"video":str(source)})
            start=evaluation.keyframe_start("ffprobe",source,1.4)
            self.assertLessEqual(start,1.4)
            bad=out/"old_picture.mkv"
            subprocess.run(["ffmpeg","-v","error","-ss","1.4","-i",str(source),"-t","1",
                            "-c:v","copy","-an",str(bad)],check=True)
            self.assertNotEqual(evaluation.first_frame_md5("ffmpeg",bad),evaluation.first_frame_md5("ffmpeg",source,1.4))
            picture,check=evaluation.comparison_picture(out,{"baseline":str(baseline),"interval":[1.4,2.4],"source":str(bad)},
                                                        {"executables":{"ffmpeg":"ffmpeg"}},1.)
            self.assertTrue(check["first_displayed_frame_equal"])
            self.assertEqual(evaluation.first_frame_md5("ffmpeg",picture),evaluation.first_frame_md5("ffmpeg",source,1.4))
            # New preparation crops all tracks from the same actual keyframe.
            good=out/"new_picture.mkv"
            subprocess.run(["ffmpeg","-v","error","-ss",str(start),"-i",str(source),"-t","1",
                            "-c:v","copy","-an",str(good)],check=True)
            self.assertEqual(evaluation.first_frame_md5("ffmpeg",good),evaluation.first_frame_md5("ffmpeg",source,start))
