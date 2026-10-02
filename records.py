"""Record folders and EAF tier discovery for the corpus browser."""
import io
import json
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from urllib.parse import urlencode
from eaf_dataframe import eaf_dataframe
from volumes import VolumeError

AUDIO = {'.wav','.mp3','.m4a','.ogg','.flac','.aac'}


def listing(volumes, volume_id, folder=''):
    result=[]
    cursor=None
    while True:
        page=volumes.browse(volume_id,folder,cursor)
        result.extend(page['items'])
        cursor=page['next_cursor']
        if not cursor: return result


def record_index(volumes):
    mounts=[]
    for v in volumes.list():
        try:
            items=listing(volumes,v['id'])
            mounts.append({'id':v['id'],'name':v['name'], 'records':[
                {'record_id':i['name']} for i in items if i['folder']],
                'loose_files':sum(not i['folder'] for i in items)})
        except VolumeError as e:
            mounts.append({'id':v['id'],'name':v['name'],'records':[],'error':str(e)})
    return mounts


def load_record(volumes, volume_id, record_id, eaf=None, tier=None, translation=None):
    if not record_id or '/' in record_id or '\\' in record_id or record_id in ('.','..'):
        raise VolumeError('Select a top-level record folder.')
    files=[i for i in listing(volumes,volume_id,record_id) if not i['folder']]
    eafs=[f['path'] for f in files if PurePosixPath(f['path']).suffix.lower()=='.eaf']
    if not eafs: raise VolumeError('This record has no EAF annotation file.')
    eaf=eaf or eafs[0]
    if eaf not in eafs: raise VolumeError('EAF file is not in this record.')
    document=volumes.open_document(volume_id,eaf)
    if document['kind']!='text':raise VolumeError('The EAF file must be XML text.')
    text=document['text']
    if '<!DOCTYPE' in text.upper():raise VolumeError('EAF documents containing a DOCTYPE are not supported.')
    root=ET.fromstring(text)
    tiers=root.findall('TIER')
    roots=[t for t in tiers if not t.get('PARENT_REF') and t.find('./ANNOTATION/ALIGNABLE_ANNOTATION') is not None]
    if not roots:raise VolumeError('No timed transcription tier found.')
    tier=tier or roots[0].get('TIER_ID')
    if tier not in [t.get('TIER_ID') for t in roots]:raise VolumeError('Unknown transcription tier.')
    languages={l.get('LANG_ID'):l.get('LANG_LABEL') or l.get('LANG_ID') for l in root.findall('LANGUAGE')}
    translations=[]
    for t in tiers:
        name=t.get('TIER_ID','')
        hint=(name+' '+t.get('LINGUISTIC_TYPE_REF','')).casefold()
        if t.get('PARENT_REF')==tier and (any(w in hint for w in ['translat','traduc','traduç']) or t.get('LANG_REF')):
            lang=t.get('LANG_REF')
            translations.append({'id':name,'label':f"{languages.get(lang,lang)} · {name}" if lang else name})
    translation=translation if translation is not None else (translations[0]['id'] if translations else '')
    if translation and translation not in [t['id'] for t in translations]:raise VolumeError('Unknown translation tier.')
    # Limit to the selected root's descendants; unrelated speakers may have different hierarchies.
    included={tier}
    while True:
        extra={t.get('TIER_ID') for t in tiers if t.get('PARENT_REF') in included}
        if extra<=included:break
        included|=extra
    for t in tiers:
        if t.get('TIER_ID') not in included:root.remove(t)
    df=eaf_dataframe(io.StringIO(ET.tostring(root,encoding='unicode')),transcript_tier=tier,translation_tier=translation)
    if df.empty:raise VolumeError('The selected tier has no annotations.')
    audio=[f for f in files if PurePosixPath(f['path']).suffix.lower() in AUDIO]
    for a in audio:
        a['url']='/api/record-audio?'+urlencode({'volume_id':volume_id,'path':a['path']})
    meta={'record_id':record_id,'volume_id':volume_id,'eaf':eaf,'eafs':eafs,'tier':tier,
          'transcript_tiers':[t.get('TIER_ID') for t in roots], 'translation':translation,
          'translations':translations,'audio':audio,'files':files}
    volume=next(v for v in volumes.list() if v['id']==volume_id)
    source=volume['location'].rstrip('/')+'/'+eaf
    return df, source, meta
