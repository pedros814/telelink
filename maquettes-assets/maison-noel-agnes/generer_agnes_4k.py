#!/usr/bin/env python3
"""Generate 12 genuine native-4K Christmas photos with Agnes; needs own key in environment."""
import os,json,time,pathlib,io,base64,argparse,zipfile
import requests
from PIL import Image
P=pathlib.Path(__file__).resolve().parent
DATA=json.loads((P/'PROMPTS_AGNES_4K.json').read_text(encoding='utf-8'))
parser=argparse.ArgumentParser()
parser.add_argument('--dry-run',action='store_true')
parser.add_argument('--limit',type=int,default=12)
args=parser.parse_args()
if args.dry_run:
 for rec in DATA[:args.limit]: print(rec['universe'],rec['file'])
 raise SystemExit(0)
key=os.getenv('AGNES_AI_API_KEY') or os.getenv('AGNES_API_KEY')
if not key: raise SystemExit('Cle Agnes image absente: fournir AGNES_AI_API_KEY au process Claude, sans jamais imprimer la valeur.')
base=P/'AGNES_4K_GENERATED';base.mkdir(exist_ok=True)
manifest=[]
for index,rec in enumerate(DATA[:args.limit]):
 folder=base/rec['universe'];folder.mkdir(exist_ok=True)
 target=folder/(rec['file']+'.png')
 if target.exists():
  print('EXISTE',target.name,flush=True)
  continue
 body={'model':'agnes-image-2.5-flash','prompt':rec['prompt'],'size':'4K','ratio':'4:3','extra_body':{'response_format':'url'}}
 for attempt in range(4):
  try:
   response=requests.post('https://apihub.agnes-ai.com/v1/images/generations',json=body,headers={'Authorization':'Bearer '+key},timeout=360)
   if response.status_code==429:
    delay=max(65,int(response.headers.get('Retry-After') or 65));print('Limite Agnes; nouvelle tentative apres delai serveur',flush=True);time.sleep(delay);continue
   response.raise_for_status();data=response.json()['data'][0]
   if data.get('url'):
    binary=requests.get(data['url'],timeout=180).content
   elif data.get('b64_json'):
    binary=base64.b64decode(data['b64_json'])
   else: raise RuntimeError('Reponse Agnes sans image')
   im=Image.open(io.BytesIO(binary)).convert('RGB')
   if im.width < 4000 or im.height < 3000: raise RuntimeError('Dimensions natives inattendues: '+str(im.size))
   im.save(target,format='PNG',optimize=True)
   manifest.append({'name':rec['file'],'universe':rec['universe'],'dimensions':list(im.size),'provider':'Agnes AI','model':'agnes-image-2.5-flash'})
   print('OK',target.name,im.size,flush=True)
   break
  except Exception as exc:
   print('Erreur image',rec['file'],type(exc).__name__,str(exc)[:180],flush=True)
   if attempt==3:raise
   time.sleep(65)
 (base/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 if index<len(DATA)-1: time.sleep(65) # document Agnes 4K: environ 1 appel/minute
z=P/'NOEL_AGNES_12_PHOTOS_NATIVE_4K.zip'
with zipfile.ZipFile(z,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
 for p in base.rglob('*'):
  if p.is_file(): archive.write(p,arcname=p.relative_to(base))
print('ARCHIVE',z,'IMAGES',len(list(base.rglob('*.png'))))
