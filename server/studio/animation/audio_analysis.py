"""Measured local audio timing without speech inference or provider calls."""
import array,math,statistics,subprocess
from .. import media
from ..jobs import JobError
from ..osenv import NO_WINDOW
from .render import asset_path,probe_audio

def analyze(source,sid):
    path=asset_path(source,sid);duration=probe_audio(path);rate=22050;hop=220
    result=subprocess.run([media.ffmpeg(),'-v','error','-protocol_whitelist','file,pipe','-i',str(path),'-t','180','-f','s16le','-ac','1','-ar',str(rate),'pipe:1'],capture_output=True,timeout=60,creationflags=NO_WINDOW)
    if result.returncode:raise JobError('Audio could not be decoded for timing analysis')
    samples=array.array('h');samples.frombytes(result.stdout)
    if __import__('sys').byteorder!='little':samples.byteswap()
    if not samples:raise JobError('Audio contains no decoded samples')
    rms=[math.sqrt(sum(v*v for v in samples[i:i+hop])/len(samples[i:i+hop]))/32768 for i in range(0,len(samples),hop)]
    onsets=[max(0,value-(rms[i-1] if i else value)) for i,value in enumerate(rms)]
    floor=statistics.median(rms);threshold=max(.008,floor*.25);candidates=sorted([(value,i) for i,value in enumerate(onsets) if value>threshold],reverse=True);hits=[]
    for strength,index in candidates:
        if all(abs(index-other)>int(.15*rate/hop) for _,other in hits):hits.append((strength,index))
        if len(hits)>=64:break
    hits.sort(key=lambda entry:entry[1]);energy=sum(v*v for v in onsets);tempo=None;confidence=0
    if energy>1e-8 and len(hits)>=4:
        scores=[]
        for lag in range(round(rate/hop*60/200),round(rate/hop*60/45)+1):
            value=sum(onsets[i]*onsets[i-lag] for i in range(lag,len(onsets)))/energy
            scores.append((value,lag))
        score,lag=max(scores);confidence=round(min(1,score),3)
        if score>=.15:tempo=round(60*rate/hop/lag,1)
    seconds=[]
    per_second=rate/hop
    for i in range(math.ceil(duration)):
        chunk=rms[round(i*per_second):round((i+1)*per_second)]
        if chunk:seconds.append({'start':i,'end':round(min(i+1,duration),3),'rms':round(math.sqrt(sum(v*v for v in chunk)/len(chunk)),5)})
    pauses=[];begin=None;quiet=max(.003,floor*.18)
    for i,value in enumerate(rms+[1]):
        if value<quiet and begin is None:begin=i
        if value>=quiet and begin is not None:
            if (i-begin)*hop/rate>=.18:pauses.append({'start':round(begin*hop/rate,3),'end':round(min(i*hop/rate,duration),3)})
            begin=None
    peak=max(abs(v) for v in samples)/32768
    return {'source':source,'duration':duration,'peak_dbfs':round(20*math.log10(max(peak,1e-9)),2),'tempo_estimate_bpm':tempo,'tempo_confidence':confidence,'hits':[{'time':round(index*hop/rate,3),'strength':round(strength,5)} for strength,index in hits],'pauses':pauses,'energy_by_second':seconds,'speech_transcribed':False,'note':'Hits are energy onsets, not guaranteed musical beats. Tempo is an estimate and may be an octave alias; verify against the track. This analysis does not transcribe speech or align individual words.'}
