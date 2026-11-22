"""Daily Japanese trivia video. Requires Gemini free-tier API key and network.
Video is animated typography, NOT AI-generated photographic footage.
"""
import os, json, re, random, subprocess, asyncio, datetime, pathlib, textwrap
import requests
from PIL import Image, ImageDraw, ImageFont
import edge_tts

ROOT=pathlib.Path(__file__).parent
OUT=ROOT/'output'; OUT.mkdir(exist_ok=True)
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
if not pathlib.Path(FONT).exists():
    FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
DATE=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
CATEGORIES=['科学','宇宙','生物','歴史','食べ物','地理','技術','自然']

def ff(*args):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],check=True)

def fetch_script():
    key=os.environ.get('GEMINI_API_KEY')
    if not key: raise RuntimeError('GEMINI_API_KEY secret is missing. No paid fallback is used.')
    category=CATEGORIES[DATE.toordinal()%len(CATEGORIES)]
    prompt=f'''あなたは日本語の科学雑学編集者。{DATE}用、ジャンル{category}。以下の条件を厳守。必ずJSONのみ返答。
事実としてよく確立した身近で意外な豆知識を1つ選び、誇張しない。毎日の変化のため題材の候補は日付を種に変える。出典は必ず公式の一次情報または公的機関の「実在が確実なトップレベルURL」だけを提示し、未確認の詳細URLは作らない。これは公開前に人間が検証するドラフト。
JSON形式: {{"title":"35文字以内","narration":"自然な日本語で160〜210文字、句点を使い6〜9文、冒頭で疑問を投げかけ最後に結論","fact_check":"公開前に確認すべき中心主張","source_urls":["https://..."],"description":"短い概要欄","hashtags":["#雑学","#科学"]}}'''
    url='https://generativelanguage.googleapis.com/v1beta/models/'+os.getenv('GEMINI_MODEL','gemini-3.5-flash-lite')+':generateContent'
    r=requests.post(url,params={'key':key},json={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseMimeType':'application/json','temperature':0.85}},timeout=70)
    if not r.ok: raise RuntimeError(f'Gemini API returned {r.status_code}: {r.text[:400]}')
    raw=r.json()['candidates'][0]['content']['parts'][0]['text']
    data=json.loads(raw)
    if not data.get('narration') or not data.get('title'): raise ValueError('Incomplete AI response')
    return data

def wrap_japanese(text,n=12):
    return '\n'.join(text[i:i+n] for i in range(0,len(text),n))

def draw_card(path,text,idx,total):
    im=Image.new('RGB',(1080,1920),(10,19,35)); d=ImageDraw.Draw(im)
    random.seed(idx+DATE.toordinal()); blobs=[(random.randint(-200,900),random.randint(-100,1750),random.randint(250,650)) for _ in range(8)]
    for x,y,r in blobs:
        d.ellipse((x,y,x+r,y+r),fill=(18+idx*3,37+idx*3,62+idx*2))
    d.rounded_rectangle((68,85,1012,200),radius=30,fill=(30,51,76))
    fsmall=ImageFont.truetype(FONT,48); fbig=ImageFont.truetype(FONT,76)
    d.text((95,111),'今日の雑学  |  SCIENCE SHORTS',font=fsmall,fill=(240,196,73))
    lines=wrap_japanese(text,12).split('\n')
    y=760-(len(lines)-1)*58
    for line in lines:
        box=d.textbbox((0,0),line,font=fbig); w=box[2]
        d.text(((1080-w)//2,y),line,font=fbig,fill='white',stroke_width=3,stroke_fill=(5,11,23)); y+=116
    d.rounded_rectangle((70,1680,1010,1701),radius=10,fill=(50,65,86))
    d.rounded_rectangle((70,1680,70+int(940*(idx+1)/total),1701),radius=10,fill=(250,198,68))
    d.text((72,1745),'AI生成の下書き｜投稿前に事実確認',font=ImageFont.truetype(FONT,37),fill=(180,190,205))
    im.save(path)

async def make_speech(segments):
    voice='ja-JP-NanamiNeural'
    durations=[]
    for i,s in enumerate(segments):
        mp3=OUT/f'voice_{i:02}.mp3'
        await edge_tts.Communicate(s,voice,rate='+12%').save(str(mp3))
        p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(mp3)],capture_output=True,text=True,check=True)
        durations.append(float(p.stdout.strip())+0.35)
    return durations

def main():
    data=fetch_script()
    (OUT/'review.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    text=data['narration'].replace('！','！|').replace('？','？|').replace('。','。|')
    sentences=[s.strip() for s in text.split('|') if s.strip()]
    # Longer sentences are split for readable on-screen cards.
    segments=[]
    for s in sentences:
        if len(s)>35:
            while len(s)>35:
                cut=max(s.rfind('、',0,30),s.rfind('，',0,30))
                if cut<10: cut=28
                else: cut+=1
                segments.append(s[:cut]);s=s[cut:]
        if s: segments.append(s)
    durations=asyncio.run(make_speech(segments))
    clips=[]
    for i,(s,duration) in enumerate(zip(segments,durations)):
        png=OUT/f'card_{i:02}.png';mp3=OUT/f'voice_{i:02}.mp3';mp4=OUT/f'clip_{i:02}.mp4'
        draw_card(png,s,i,len(segments))
        ff('-loop','1','-framerate','30','-i',png,'-i',mp3,'-filter_complex',f'[0:v]scale=1080:1920,zoompan=z=min(zoom+0.0003\\,1.06):d=1:s=1080x1920:fps=30,format=yuv420p[v];[1:a]apad=pad_dur=0.35[a]','-map','[v]','-map','[a]','-t',f'{duration:.3f}','-c:v','libx264','-preset','ultrafast','-crf','27','-r','30','-c:a','aac','-b:a','128k','-movflags','+faststart',mp4)
        clips.append(mp4)
    playlist=OUT/'concat.txt';playlist.write_text(''.join(f"file '{p.name}'\n" for p in clips))
    ff('-f','concat','-safe','0','-i',playlist,'-c','copy',OUT/'daily_short.mp4')
    total=sum(durations)
    (OUT/'README_REVIEW.txt').write_text(f"日付: {DATE}\n題名: {data['title']}\n推定時間: {total:.1f}秒\n必ずreview.jsonの事実・URLを確認してから公開してください。\nAIが作成した文章の正確性は保証されません。\n音声はedge-ttsの非公式接続であり、サービス側の変更で停止する場合があります。\nBGMは権利上の問題を避けるため未収録です。\n",encoding='utf-8')
    print(f'Created {OUT/"daily_short.mp4"} ({total:.1f}s)')

if __name__=='__main__': main()
