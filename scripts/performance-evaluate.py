#!/usr/bin/env python3
"""Prepare bounded isolated sources and render existing job comparisons.

Prepare/render/excerpts are offline; run-set drives the configured bin/aidub auto.
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


def keyframe_start(ffprobe, source, requested):
    data=json.loads(run_cmd([ffprobe,"-v","error","-select_streams","v:0","-read_intervals",f"{requested}%+#1",
                             "-show_entries","packet=pts_time,flags","-of","json",str(source)]).stdout)
    packet=data["packets"][0];start=float(packet["pts_time"])
    if "K" not in packet["flags"] or start > requested+1e-6 or start < 0:
        raise ValueError("Cannot establish a nonnegative copied-picture keyframe origin")
    return start


def first_frame_md5(ffmpeg, source, start=0):
    data=run_cmd([ffmpeg,"-v","error","-ss",str(start),"-i",str(source),"-map","0:v:0","-frames:v","1",
                  "-an","-f","framemd5","-"]).stdout
    return next(row.rsplit(",",1)[1].strip() for row in data.splitlines() if row and not row.startswith("#"))


def comparison_picture(out, receipt, cfg, duration):
    """MP4 edit lists preserve seek preroll; Matroska normalization did not.

    Older evaluation fixtures keep their saved samples/jobs. Comparisons recover
    the correct display origin directly from the full copied baseline picture.
    """
    baseline=Path(receipt["baseline"])
    original=Path(read_json(baseline/"manifest.json")["video"])
    source=original if original.is_file() else baseline/"output/spanish_compare.mp4"
    start=receipt["interval"][0];ffmpeg=cfg["executables"]["ffmpeg"]
    path=out/"comparison_picture.mp4"
    run_cmd([ffmpeg,"-v","error","-y","-ss",str(start),"-i",str(source),"-t",str(duration),
             "-map","0:v:0","-c:v","copy","-an","-avoid_negative_ts","disabled",str(path)])
    aligned=first_frame_md5(ffmpeg,source,start)==first_frame_md5(ffmpeg,path)
    if not aligned:
        raise ValueError("Copied comparison picture does not display the requested source frame")
    return path,{"source":str(source),"source_start":start,"first_displayed_frame_equal":aligned,
                 "pipeline_fixture_picture_replaced_for_comparison":str(source)!=receipt["source"],
                 "scope":"available saved picture; not revalidation against a missing original"}


def prepare(args):
    baseline=args.baseline.resolve(); out=args.output.resolve()
    if out==baseline or baseline in out.parents:
        raise ValueError("Evaluation output must be separate from the source job")
    out.mkdir(parents=True,exist_ok=True)
    with JobLock(baseline),JobLock(out):
        receipt=out/"passage.json"
        if receipt.is_file():
            saved=read_json(receipt)
            if saved["baseline"]!=str(baseline) or saved.get("requested_interval",saved["interval"])!=[args.start,args.end]:
                raise ValueError("Existing evaluation receipt belongs to another passage")
            print(json.dumps(saved,indent=2));return
        if not 0<=args.start<args.end or args.end-args.start>300:
            raise ValueError("Evaluation passages must be bounded to five minutes")
        reference=read_json(args.reference_config)
        cfg=apply_preset(read_json(baseline/"config.json"),load_preset("performance"))
        for key in ("reference","qwen3","schedule"):
            cfg[key]=copy.deepcopy(reference[key])
        cfg["jobs_dir"]=str((out/"jobs").resolve())
        requested_start=args.start
        duration=args.end-args.start; ffmpeg=cfg["executables"]["ffmpeg"]
        source=Path(read_json(baseline/"manifest.json")["video"])
        saved_picture=not source.is_file()
        if saved_picture:source=baseline/"output/spanish_compare.mp4"
        if not args.clone:
            # Align samples to the actual copied keyframe, so a container that
            # normalizes preroll cannot move gameplay relative to the microphone.
            args.start=keyframe_start(cfg["executables"]["ffprobe"],source,args.start)
            duration=args.end-args.start
            if duration>300:
                raise ValueError("Keyframe context makes this passage longer than five minutes")
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
            if first_frame_md5(ffmpeg,fixture)!=first_frame_md5(ffmpeg,source,args.start):
                raise ValueError("Fixture copied-picture origin disagrees with microphone crop; stop before ASR/providers")
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
             "requested_interval":[requested_start,args.end],"picture_origin":"copied_keyframe" if not args.clone else "complete_source",
             "reference_sha256":{key:sha256_file(Path(cfg["reference"][key])) for key in ("wav","text_file")},
             "limitations":["Agent cannot listen. Source spans require listening approval.",
                            "Cropped copied picture may have keyframe preroll; WAV crops are sample-exact.",
                            "A missing original cannot be revalidated against its saved extraction."]}
        write_json(receipt,doc);print(json.dumps(doc,indent=2))


def render(args):
    out=args.output.resolve(); receipt=read_json(out/"passage.json");job=Path(receipt["job"])
    with JobLock(job),JobLock(out),JobLock(Path(receipt["baseline"])):
        cfg=read_json(job/"config.json");ffmpeg=cfg["executables"]["ffmpeg"]
        summary=read_json(job/"mix/placed_summary.json");duration=summary["source_duration_sec"]
        if read_json(job/"extract/alignment.json")["offset_sec"] != 0:
            raise ValueError("Comparison renderer requires zero aligned microphone offset")
        preview=out/"previews";preview.mkdir(exist_ok=True)
        picture,picture_timing=comparison_picture(out,receipt,cfg,duration)
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
            run_cmd([ffmpeg,"-v","error","-y","-copyts","-i",str(picture),"-i",str(mixes[-1]),
                     "-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac","-b:a","192k",
                     "-avoid_negative_ts","disabled",str(preview/(label+".mp4"))])
        video_ok=all(bitstream_md5(ffmpeg,str(preview/(label+".mp4")))==bitstream_md5(ffmpeg,str(picture))
                     for label in ("spanish","prior","new"))
        if not all(first_frame_md5(ffmpeg,preview/(label+".mp4"))==first_frame_md5(ffmpeg,picture)
                   for label in ("spanish","prior","new")):
            raise ValueError("Comparison mux moved the displayed picture origin")
        ledger=read_json(job/"report/vocal_events.json") if (job/"report/vocal_events.json").exists() else {}
        prior=read_json(Path(receipt["baseline"])/"mix/placed_summary.json")
        base_raw={sha256_file(p) for p in (Path(receipt["baseline"])/"cache/synth").glob("*.wav")}
        current_raw={sha256_file(p) for p in (job/"cache/synth").glob("*.wav")}
        selected=[]
        for s in summary["segments"]:
            if not s.get("placed"):continue
            take=next((a for a in s.get("attempts",[]) if a.get("seed")==s.get("seed") and a.get("text")==s.get("english")),None)
            if take and take.get("raw_path"):selected.append(sha256_file(Path(take["raw_path"])))
        a,b=receipt["interval"]
        old=[s for s in prior["segments"] if a<=s["start"]<b]
        report={"interval":receipt["interval"],"new_status":read_json(job/"manifest.json")["state"],
                "new_validation":str(job/"report/validation.json"),"vocal_events":ledger,
                "reference_changed_from_long_baseline":prior["reference_sha256"]!=summary["reference_sha256"],
                "baseline_cues":[{k:s.get(k) for k in ("id","start","end","spanish","english","placed")} for s in old],
                "new_cues":[{k:s.get(k) for k in ("id","start","end","spanish","english","placed","placement_start","placement_end","timing_error")} for s in summary["segments"]],
                "synthesis":{"fresh":summary["n_synth_fresh"],"cache_hits":summary["n_synth_cache_hits"],
                             "raw_inventory":{"baseline_unique_waveforms":len(base_raw),"current_unique_waveforms":len(current_raw),
                                              "additional_unique_waveforms":len(current_raw-base_raw),
                                              "selected_from_baseline":sum(h in base_raw for h in selected),
                                              "selected_new":sum(h not in base_raw for h in selected),
                                              "scope":"current cache versus baseline, including unused attempts; not backend invocation count"}},
                "copied_video_equal":video_ok,"picture_timing":picture_timing,
                "encoded_audio":{label:encoded_audio_metrics(ffmpeg,str(preview/(label+".mp4"))) for label in ("spanish","prior","new")},
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


def excerpts(args):
    out=args.output.resolve();receipt=read_json(out/"passage.json");job=Path(receipt["job"])
    origin,end=receipt["interval"]
    if not origin<=args.start<args.end<=end:
        raise ValueError("Excerpt must lie inside the evaluated source interval")
    with JobLock(job),JobLock(out):
        cfg=read_json(job/"config.json");ffmpeg=cfg["executables"]["ffmpeg"]
        directory=out/"excerpts"/f"{args.start:09.3f}-{args.end:09.3f}"
        directory.mkdir(parents=True,exist_ok=True);local=args.start-origin;duration=args.end-args.start
        page=f'<!doctype html><meta charset="utf-8"><h1>Original recording {args.start:.3f}–{args.end:.3f}s</h1><p>No agent listening or perceptual approval. WAV boundaries are sample accurate. Video uses copied packets with MP4 edit-list preroll.</p>'
        checks={}
        for label,voice in (("spanish","spanish_mic"),("prior","prior_voice"),("new","new_voice")):
            crop(out/f"previews/{voice}.wav",directory/f"{label}_voice.wav",local,duration)
            crop(out/f"previews/{label}_mix.wav",directory/f"{label}_mix.wav",local,duration)
            picture=directory/f"{label}.mp4"
            run_cmd([ffmpeg,"-v","error","-y","-ss",str(local),"-i",str(out/"comparison_picture.mp4"),
                     "-i",str(directory/f"{label}_mix.wav"),"-t",str(duration),"-map","0:v:0","-map","1:a:0",
                     "-c:v","copy","-c:a","aac","-b:a","192k","-avoid_negative_ts","disabled",str(picture)])
            checks[label]=dict(first_displayed_frame_equal=first_frame_md5(ffmpeg,picture)==first_frame_md5(ffmpeg,out/"comparison_picture.mp4",local),
                               voice_sha256=sha256_file(directory/f"{label}_voice.wav"),mix_sha256=sha256_file(directory/f"{label}_mix.wav"))
            page+=f'<h2>{label}</h2><video controls preload="metadata" width="720" src="{label}.mp4"></video><p>Voice alone: <audio controls preload="none" src="{label}_voice.wav"></audio></p>'
        if not all(c["first_displayed_frame_equal"] for c in checks.values()):
            raise ValueError("Excerpt copied picture origin mismatch")
        write_json(directory/"evidence.json",dict(interval=[args.start,args.end],checks=checks,listening_approved=False))
        (directory/"index.html").write_text(page)
        print(directory/"index.html")


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
                "retained":report.get("n_segments"),"translated":sum(bool(s.get("english")) for s in manifest.get("timeline",[])),
                "placed":report.get("n_placed"),"omitted":report.get("omitted"),
                "synthesis":c.get("synthesis"),"vocal_events":report.get("vocal_events"),
                "source_uncertainties":report.get("source_uncertainties"),"transcription_drops":corrections.get("dropped",[]),
                "source_text_diff":diff,"source_text_diff_scope":"ASR/segmentation differences, not listening ground truth",
                "settings_match_approved":all(cfg[k]==reference[k] for k in ("reference","qwen3","schedule")),
                "reference_hashes":{k:sha256_file(Path(cfg["reference"][k])) for k in ("wav","text_file")},
                "failed_required_checks":[x for x in report.get("checks",[]) if x.get("required",True) and x.get("ok") is not True],
                "copied_video_equal":c.get("copied_video_equal"),"picture_timing":c.get("picture_timing")}
        records.append(record)
        link=f'{receipt.parent.name}/index.html' if c else f'{receipt.parent.name}/run.log'
        page+=f'<p><a href="{html.escape(link)}">{a:.3f}–{b:.3f}s: {html.escape(d["name"])}</a> — {html.escape(manifest["state"])}; placed {report.get("n_placed","unavailable")}/{report.get("n_segments","unavailable")}</p>'
        for excerpt in sorted(receipt.parent.glob("excerpts/*/index.html")):
            page+=f'<p>Short comparison: <a href="{excerpt.relative_to(root)}">{excerpt.parent.name}s</a></p>'
    page+='<h2>Identical cached takes / selection controls</h2>'
    for old_name in ("cached-minute","cached-long-600-790"):
        name=old_name+"-final" if (root/(old_name+"-final")/"evidence.json").exists() else old_name
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
    excerpt=sub.add_parser("excerpts");excerpt.add_argument("--start",type=float,required=True);excerpt.add_argument("--end",type=float,required=True)
    for command in (p,sub.add_parser("render"),run,summary,excerpt):command.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    {"prepare":prepare,"render":render,"run-set":run_set,"summarize":summarize,"excerpts":excerpts}[args.action](args)
