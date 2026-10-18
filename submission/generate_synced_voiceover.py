import asyncio
import os
import ssl
import struct
import subprocess
import wave
import edge_tts

# Corporate SSL bypass for edge_tts
ssl._create_default_https_context = ssl._create_unverified_context
import edge_tts.communicate, edge_tts.constants
edge_tts.constants._SSL_CTX = ssl._create_unverified_context()
edge_tts.communicate._SSL_CTX = ssl._create_unverified_context()

FFMPEG = r"C:\Users\703292978\Downloads\node-v24.21.0-win-x64\node-v24.21.0-win-x64\ffmpeg.exe"
VOICE = "en-US-ChristopherNeural"  # Professional, articulate, natural human narrator

SEGMENTS = [
    {
        "id": "seg01_intro",
        "start_sec": 1.0,
        "text": "Welcome to CargoClear, an agentic pre-submission customs compliance workbench powered by Google Cloud Vertex AI and Gemini 2.5 Flash, providing verified decision support for licensed brokers."
    },
    {
        "id": "seg02_case_c_upload",
        "start_sec": 14.5,
        "text": "In Case C, an export from India to Singapore, three trade documents are uploaded: an invoice, bill of lading, and packing list. We run analysis to extract fields and evaluate cross-border customs rules in real time."
    },
    {
        "id": "seg03_case_c_missing",
        "start_sec": 39.8,
        "text": "CargoClear immediately flags missing evidence: the declared HS code mandates a certified Mill Test Certificate. When the agent supplies the certificate, the bundle re-evaluates automatically."
    },
    {
        "id": "seg04_case_c_compliant",
        "start_sec": 69.3,
        "text": "With the certificate verified, status transitions to Compliant for Submission. The Reasoning Delta transparently details what changed, and the SHA-256 audit ledger confirms procedural integrity."
    },
    {
        "id": "seg05_case_d_upload",
        "start_sec": 87.0,
        "text": "Now let's examine Case D, an industrial steel pipe shipment imported into India declared under non-alloy HS 7304.19. All four trade documents are submitted for multimodal analysis."
    },
    {
        "id": "seg06_case_d_contradiction",
        "start_sec": 126.4,
        "text": "Contradiction detected: heat TH-77121 reports 0.35% chromium, classifying this as alloy steel under Note 1."
    },
    {
        "id": "seg07_correction",
        "start_sec": 137.0,
        "text": "The broker inspects the certificate, corrects chromium to 0.28%, and logs the reason. The correction remains pending until recomputed."
    },
    {
        "id": "seg08_recompute",
        "start_sec": 147.5,
        "text": "Recompute instantly executes the deterministic rules with zero LLM tokens, updating status to Specialist Review Required."
    },
    {
        "id": "seg09_prefill_audit_close",
        "start_sec": 156.5,
        "text": "Finally, the Customs Pre-Fill Pack exports grounded page citations, while the audit chain is digitally signed by Google Cloud KMS. Built on Cloud Run with scale-to-zero efficiency, CargoClear delivers fast, verifiable compliance for cross-border trade."
    }
]

async def synthesize_all():
    os.makedirs("submission/audio_segments", exist_ok=True)
    for seg in SEGMENTS:
        mp3_path = f"submission/audio_segments/{seg['id']}.mp3"
        print(f"Synthesizing {seg['id']}...")
        comm = edge_tts.Communicate(seg["text"], VOICE, rate="+5%")
        await comm.save(mp3_path)
        
        # Convert to 44.1kHz mono WAV via ffmpeg
        wav_path = f"submission/audio_segments/{seg['id']}.wav"
        cmd = [FFMPEG, "-y", "-i", mp3_path, "-ac", "1", "-ar", "44100", wav_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        with wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            dur = n_frames / wf.getframerate()
            seg["duration"] = dur
            seg["wav_path"] = wav_path
            print(f"  -> Duration: {dur:.2f}s | Starts at {seg['start_sec']}s | Ends at {seg['start_sec'] + dur:.2f}s")

def build_master_track(total_duration_sec=172.0):
    sample_rate = 44100
    total_samples = int(total_duration_sec * sample_rate)
    master_samples = [0] * total_samples
    
    # Check for overlaps
    for i in range(len(SEGMENTS) - 1):
        curr = SEGMENTS[i]
        nxt = SEGMENTS[i+1]
        curr_end = curr["start_sec"] + curr["duration"]
        if curr_end > nxt["start_sec"]:
            print(f"WARNING: Segment {curr['id']} ends at {curr_end:.2f}s but {nxt['id']} starts at {nxt['start_sec']:.2f}s!")
        else:
            print(f"OK: {curr['id']} ends at {curr_end:.2f}s -> Gap of {nxt['start_sec'] - curr_end:.2f}s before {nxt['id']}")

    for i, seg in enumerate(SEGMENTS):
        start_sample = int(seg["start_sec"] * sample_rate)
        with wave.open(seg["wav_path"], "rb") as wf:
            raw_bytes = wf.readframes(wf.getnframes())
            # 16-bit signed PCM
            samples = struct.unpack(f"<{len(raw_bytes)//2}h", raw_bytes)
            
        print(f"Mixing {seg['id']} at sample {start_sample} ({seg['start_sec']}s)...")
        for j, s in enumerate(samples):
            idx = start_sample + j
            if idx < total_samples:
                # Add and clamp
                val = master_samples[idx] + s
                master_samples[idx] = max(-32768, min(32767, val))

    out_wav = "submission/voiceover_synced.wav"
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        raw_out = struct.pack(f"<{len(master_samples)}h", *master_samples)
        wf.writeframes(raw_out)
    
    print(f"\nSuccessfully generated synchronized master audio: {out_wav} ({total_duration_sec:.2f}s)")

if __name__ == "__main__":
    asyncio.run(synthesize_all())
    last_seg = SEGMENTS[-1]
    min_dur = last_seg["start_sec"] + last_seg["duration"] + 3.0
    total_dur = max(172.0, min_dur)
    build_master_track(total_dur)
