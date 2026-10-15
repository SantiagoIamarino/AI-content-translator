#!/usr/bin/env python3
"""Prepare bounded isolated evaluation sources and render existing job comparisons.

No provider/TTS calls: run the resulting job using this checkout's bin/aidub auto.
Original jobs remain locked for reads. Media/configuration stay in ignored output.
"""
import argparse
import copy
import difflib
import html
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from aidub.config import apply_preset, load_preset
from aidub.job import JobLock
from aidub.media import run_cmd, bitstream_md5, encoded_audio_metrics
from aidub.util import read_json, write_json, sha256_file


def crop(src, dst, start, duration):
    with sf.SoundFile(src) as f:
        f.seek(round(start*f.samplerate))
        x=f.read(round(duration*f.samplerate),dtype="float32",always_2d=True)
        sf.write(dst,x,f.samplerate,subtype="FLOAT")


def prepare(args):
    baseline=args.baseline.resolve(); out=args.output.resolve()
    if out==baseline or baseline in out.parents:
        raise ValueError("Evaluation output must be separate from the source job")
    out.mkdir(parents=True,exist_ok=True)
    with JobLock(baseline),JobLock(out):
        receipt=out/"passage.json"
        if receipt.is_file():
            saved=read_json(receipt)
            if saved["baseline"]!=str(baseline) or saved["interval"]!=[args.start,args.end]:
                raise ValueError("Existing evaluation receipt belongs to another passage")
            print(json.dumps(saved,indent=2));return
        if not 0<=args.start<args.end or args.end-args.start>300:
            raise ValueError("Evaluation passages must be bounded to five minutes")
        reference=read_json(args.reference_config)
        cfg=apply_preset(read_json(baseline/"config.json"),load_preset("performance"))
        for key in ("reference","qwen3","schedule"):
            cfg[key]=copy.deepcopy(reference[key])
        cfg["jobs_dir"]=str((out/"jobs").resolve())
        duration=args.end-args.start; ffmpeg=cfg["executables"]["ffmpeg"]
        source=Path(read_json(baseline/"manifest.json")["video"])
        saved_picture=not source.is_file()
        if saved_picture:source=baseline/"output/spanish_compare.mp4"
        if args.clone:
            if args.start!=0:
                raise ValueError("A clone preserves the complete source, not a shifted crop")
            dest=out/"jobs"/args.name
            shutil.copytree(baseline,dest)
            for path in dest.rglob("*.json"):
                content=path.read_text(); updated=content.replace(str(baseline),str(dest))
                if updated!=content:path.write_text(updated)
            cfg["source_video"]=str(source)
            if args.annotations:
                cfg["source_events"]["annotations_file"]=str(args.annotations.resolve())
            write_json(dest/"config.json",cfg)
        else:
            for role in ("mic","game"):
                crop(baseline/f"extract/{role}_raw.wav",out/f"{role}.wav",args.start,duration)
            picture=out/"picture.mkv"
            run_cmd([ffmpeg,"-v","error","-y","-ss",str(args.start),"-i",str(source),"-t",str(duration),
                     "-map","0:v:0","-c:v","copy","-an",str(picture)])
            fixture=out/"source.mkv"
            # Original mic and game retain their sample clock. Track ordinals
            # match the source convention: mixed=0, game=1, mic=2.
            run_cmd([ffmpeg,"-v","error","-y","-i",str(picture),"-i",str(out/"mic.wav"),"-i",str(out/"game.wav"),
                     "-filter_complex","[1:a][2:a]amix=inputs=2:normalize=0[m]","-map","0:v:0","-map","[m]",
                     "-map","2:a:0","-map","1:a:0","-c:v","copy","-c:a","pcm_s16le",str(fixture)])
            if bitstream_md5(ffmpeg,str(picture))!=bitstream_md5(ffmpeg,str(fixture)):
                raise ValueError("Fixture picture changed during mux")
            cfg["audio_mapping"].update(mic_ordinal=2,game_ordinal=1,mixed_ordinal=0)
            cfg["export"]={"container":"mkv"}  # comparison track is lossless PCM
            cfg["source_video"]=str(fixture)
        crop(baseline/"output/english_voice.wav",out/"prior_voice.wav",args.start,duration)
        crop(baseline/"output/english_mix.wav",out/"prior_mix.wav",args.start,duration)
        if args.clone:
            crop(baseline/"extract/mic_raw.wav",out/"mic.wav",args.start,min(duration,sf.info(baseline/"extract/mic_raw.wav").duration))
            crop(baseline/"extract/game_raw.wav",out/"game.wav",args.start,min(duration,sf.info(baseline/"extract/game_raw.wav").duration))
        write_json(out/"config.local.json",cfg)
        doc={"baseline":str(baseline),"interval":[args.start,args.end],"name":args.name,
             "config":str(out/"config.local.json"),"source":cfg["source_video"],
             "job":str(out/"jobs"/args.name),"picture_from_saved_copy":saved_picture,
             "reference_sha256":{key:sha256_file(Path(cfg["reference"][key])) for key in ("wav","text_file")},
             "limitations":["Agent cannot listen. Source spans require listening approval.",
                            "Cropped copied picture may have keyframe preroll; WAV crops are sample-exact.",
                            "A missing original cannot be revalidated against its saved extraction."]}
        write_json(receipt,doc);print(json.dumps(doc,indent=2))


def render(args):
    out=args.output.resolve(); receipt=read_json(out/"passage.json");job=Path(receipt["job"])
    with JobLock(job),JobLock(out):
        cfg=read_json(job/"config.json");ffmpeg=cfg["executables"]["ffmpeg"]
        summary=read_json(job/"mix/placed_summary.json");duration=summary["source_duration_sec"]
        if read_json(job/"extract/alignment.json")["offset_sec"] != 0:
            raise ValueError("Comparison renderer requires zero aligned microphone offset")
        preview=out/"previews";preview.mkdir(exist_ok=True)
        frames=round(duration*48000)
        # Baseline crop and job PCM must have exactly the same displayed length.
        for source,dest in [(out/"mic.wav",preview/"spanish_mic.wav"),(out/"prior_voice.wav",preview/"prior_voice.wav"),
                            (job/"output/english_voice.wav",preview/"new_voice.wav")]:
            x,sr=sf.read(source,dtype="float32",always_2d=True)
            x=np.pad(x[:frames],((0,max(0,frames-len(x))),(0,0)))
            sf.write(dest,x,sr,subtype="FLOAT")
        game,sr=sf.read(job/"extract/game_raw.wav",dtype="float32",always_2d=True)
        game=np.pad(game[:frames],((0,max(0,frames-len(game))),(0,0)))
        mixes=[]
        for label in ("spanish","prior","new"):
            voice,vsr=sf.read(preview/("spanish_mic.wav" if label=="spanish" else label+"_voice.wav"),dtype="float32",always_2d=True)
            if vsr!=sr:raise ValueError("Preview sample rate mismatch")
            mix=game+voice.mean(axis=1)[:,None]
            if label=="new":
                actual,actual_sr=sf.read(job/"output/english_mix.wav",dtype="float32",always_2d=True)
                if actual_sr!=sr or actual.shape!=mix.shape or not np.array_equal(actual,mix):
                    raise ValueError("Comparison mix disagrees with the validated pipeline mix")
            sf.write(preview/(label+"_mix.wav"),mix,sr,subtype="FLOAT");mixes.append(preview/(label+"_mix.wav"))
            run_cmd([ffmpeg,"-v","error","-y","-i",receipt["source"],"-i",str(mixes[-1]),
                     "-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","192k",str(preview/(label+".mp4"))])
        video_ok=all(bitstream_md5(ffmpeg,str(preview/(label+".mp4")))==bitstream_md5(ffmpeg,receipt["source"])
                     for label in ("spanish","prior","new"))
        ledger=read_json(job/"report/vocal_events.json") if (job/"report/vocal_events.json").exists() else {}
        prior=read_json(Path(receipt["baseline"])/"mix/placed_summary.json")
        a,b=receipt["interval"]
        old=[s for s in prior["segments"] if a<=s["start"]<b]
        report={"interval":receipt["interval"],"new_status":read_json(job/"manifest.json")["state"],
                "new_validation":str(job/"report/validation.json"),"vocal_events":ledger,
                "reference_changed_from_long_baseline":prior["reference_sha256"]!=summary["reference_sha256"],
                "baseline_cues":[{k:s.get(k) for k in ("id","start","end","spanish","english","placed")} for s in old],
                "new_cues":[{k:s.get(k) for k in ("id","start","end","spanish","english","placed","placement_start","placement_end","timing_error")} for s in summary["segments"]],
                "synthesis":{"fresh":summary["n_synth_fresh"],"cache_hits":summary["n_synth_cache_hits"]},
                "copied_video_equal":video_ok,"encoded_audio":{label:encoded_audio_metrics(ffmpeg,str(preview/(label+".mp4"))) for label in ("spanish","prior","new")},
                "limitations":receipt["limitations"]}
        write_json(out/"comparison.json",report)
        title=f"Original recording {a:.3f}–{b:.3f}s"
        page=f"<!doctype html><meta charset=utf-8><title>{title}</title><h1>{title}</h1><p>Not listening approved. {html.escape(report['new_status'])}.</p>"
        for label in ("spanish","prior","new"):
            page+=f'<h2>{label}</h2><video controls preload="metadata" width="720" src="previews/{label}.mp4"></video>'
            page+=f'<p>Voice alone: <audio controls preload="none" src="previews/{"spanish_mic" if label=="spanish" else label+"_voice"}.wav"></audio></p>'
        page+='<p><a href="comparison.json">Cue/event accounting and technical evidence</a></p>'
        (out/"index.html").write_text(page)
        print(json.dumps({"status":report["new_status"],"video":video_ok,"index":str(out/"index.html")},indent=2))


def run_set(args):
    root=args.output.resolve()
    with JobLock(root/"queue"):
        if args.wait_for_job:
            while True:
                try:
                    with JobLock(args.wait_for_job):
                        break
                except RuntimeError as exc:
                    if "Job is locked" not in str(exc):raise
                    time.sleep(5)
        receipts=sorted(root.glob("*/passage.json"))
        if args.first:
            receipts.sort(key=lambda p:read_json(p)["name"] != args.first)
        state=read_json(root/"queue/state.json") if (root/"queue/state.json").exists() else {}
        for receipt in receipts:
            p=read_json(receipt);name=p["name"];out=receipt.parent
            cfg=read_json(out/"config.local.json")
            print("evaluate",name,flush=True)
            with (out/"run.log").open("a") as log:
                code=subprocess.run(["bin/aidub","--config",str(out/"config.local.json"),"auto",p["source"],"--name",name],
                                    stdout=log,stderr=subprocess.STDOUT).returncode
            state[name]={"exit_code":code,"job":p["job"],"log":str(out/"run.log")}
            write_json(root/"queue/state.json",state)
            if code not in (0,3):
                print(name,"stopped",code,flush=True)
                continue
            render(argparse.Namespace(output=out))
            state[name]["comparison"]=str(out/"comparison.json");write_json(root/"queue/state.json",state)


def summarize(args):
    root=args.output.resolve(); records=[]
    page='<!doctype html><meta charset="utf-8"><title>Conversational performance comparisons</title><h1>Conversational performance comparisons</h1><p>Experimental results. No agent listening or perceptual approval. Times refer to the original recording; copied excerpts may include keyframe preroll.</p>'
    for receipt in sorted(root.glob("*/passage.json"),key=lambda p:read_json(p)["interval"][0]):
        d=read_json(receipt);job=Path(d["job"]);manifest=read_json(job/"manifest.json")
        c=read_json(receipt.parent/"comparison.json") if (receipt.parent/"comparison.json").exists() else {}
        report=read_json(job/"report/validation.json") if (job/"report/validation.json").exists() else {}
        cfg=read_json(job/"config.json");reference=read_json(args.reference_config)
        corrections=read_json(job/"transcribe/corrections.json") if (job/"transcribe/corrections.json").exists() else {}
        a,b=d["interval"]
        prior=read_json(Path(d["baseline"])/"mix/placed_summary.json")
        old=[s for s in prior["segments"] if a<=s["start"]<b]
        new=c.get("new_cues",[])
        old_text=" ".join(s["spanish"] for s in old).split();new_text=" ".join(s["spanish"] for s in new).split()
        diff=[dict(op=op,before=old_text[i:j],after=new_text[k:l]) for op,i,j,k,l in difflib.SequenceMatcher(None,old_text,new_text).get_opcodes() if op!="equal"]
        record={"name":d["name"],"interval":[a,b],"status":manifest["state"],"error":manifest.get("error"),
                "preview":str(receipt.parent/"index.html") if c else None,
                "retained":report.get("n_segments"),"placed":report.get("n_placed"),"omitted":report.get("omitted"),
                "synthesis":c.get("synthesis"),"vocal_events":report.get("vocal_events"),
                "source_uncertainties":report.get("source_uncertainties"),"transcription_drops":corrections.get("dropped",[]),
                "source_text_diff":diff,"source_text_diff_scope":"ASR/segmentation differences, not listening ground truth",
                "settings_match_approved":all(cfg[k]==reference[k] for k in ("reference","qwen3","schedule")),
                "reference_hashes":{k:sha256_file(Path(cfg["reference"][k])) for k in ("wav","text_file")},
                "failed_required_checks":[x for x in report.get("checks",[]) if x.get("required",True) and x.get("ok") is not True],
                "copied_video_equal":c.get("copied_video_equal")}
        records.append(record)
        link=f'{receipt.parent.name}/index.html' if c else f'{receipt.parent.name}/run.log'
        page+=f'<p><a href="{html.escape(link)}">{a:.3f}–{b:.3f}s: {html.escape(d["name"])}</a> — {html.escape(manifest["state"])}; placed {report.get("n_placed","unavailable")}/{report.get("n_segments","unavailable")}</p>'
    page+='<h2>Identical cached takes / selection controls</h2>'
    for name in ("cached-minute","cached-long-600-790"):
        page+=f'<p>{name}: <a href="{name}/before.mp4">prior</a> · <a href="{name}/after_cached.mp4">new cached selection/processing</a> · <a href="{name}/evidence.json">evidence</a></p>'
    page+='<p><a href="results.json">Exact event, text, omission, uncertainty and settings accounting</a></p>'
    write_json(root/"results.json",{"listening_approved":False,"passages":records})
    (root/"index.html").write_text(page)
    print(root/"index.html")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="action",required=True)
    p=sub.add_parser("prepare");p.add_argument("--baseline",type=Path,required=True);p.add_argument("--reference-config",type=Path,required=True)
    p.add_argument("--name",required=True);p.add_argument("--start",type=float,default=0);p.add_argument("--end",type=float,required=True)
    p.add_argument("--clone",action="store_true");p.add_argument("--annotations",type=Path)
    run=sub.add_parser("run-set");run.add_argument("--wait-for-job",type=Path);run.add_argument("--first")
    summary=sub.add_parser("summarize");summary.add_argument("--reference-config",type=Path,required=True)
    for command in (p,sub.add_parser("render"),run,summary):command.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    {"prepare":prepare,"render":render,"run-set":run_set,"summarize":summarize}[args.action](args)
