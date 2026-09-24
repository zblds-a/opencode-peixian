"""Account-owned filename snapshots; no document content or host paths."""
import json


def filename(value):
    if not isinstance(value,str):return '文件'
    value=value.replace('\\','/').rsplit('/',1)[-1]
    return ''.join(c for c in value if ord(c)>=32 and ord(c)!=127)[:255] or '文件'


def freeze(db,uid,ids,metadata):
    # Metadata comes from the authenticated Gateway text lookup, never the caller.
    selected={item['id']:item for item in metadata or [] if item.get('id') in ids}
    result=[]
    for fid in ids:
        item=selected.get(fid)
        if item is None:
            row=db.execute('SELECT metadata FROM files WHERE uid=? AND id=?',(uid,fid)).fetchone()
            item=json.loads(row['metadata']) if row else None
        if item is None:continue
        safe={'id':fid,'name':filename(item.get('name')), **{k:item[k] for k in ('parse_status','content_sha256','text_bytes','chunk_count','usage','verified_source') if k in item}}
        result.append(safe)
        db.execute('INSERT OR IGNORE INTO files(uid,id,metadata) VALUES(?,?,?)',(uid,fid,json.dumps(safe,ensure_ascii=False)))
    return result


def project(store,uid,snapshot):
    if 'attachments' not in snapshot:
        # Legacy names were not frozen; do not parse prompts or invent filenames.
        return []
    result=[]
    allowed=set(snapshot.get('request',{}).get('file_ids',[]))
    for item in snapshot['attachments']:
        if item.get('id') not in allowed:continue
        exists=store.one('SELECT 1 AS found FROM files WHERE uid=? AND id=?',(uid,item['id']))
        result.append({**item,'name':filename(item.get('name')),'status':'available' if exists else 'unavailable'})
    return result


def material(fid, file):
    """Validate only authenticated Gateway responses, never client metadata."""
    import hashlib
    from .backend_contract import error
    if file.get('status') not in ('ready', 'partial'):
        error('file_not_ready', '所选文件尚未完成解析。', 409, {fid: 'not_ready'})
    if file.get('status') == 'partial' or file.get('truncated') is True:
        error('file_truncated', '所选文件仅完成部分解析，请拆分文件后重新上传；可在我的文件查看已提取范围', 413, {fid: 'truncated'})
    chunks=file.get('chunks', [])
    if not isinstance(chunks,list) or any(not isinstance(c,dict) or not isinstance(c.get('text'),str) for c in chunks):
        error('file_parse_invalid', '文件解析结果格式无效。', 409, {fid:'invalid_chunks'})
    content='\n'.join('[来源 '+json.dumps(c.get('source',{}),ensure_ascii=False)+'] '+c['text'] for c in chunks) if chunks else file.get('text','')
    if not isinstance(content,str) or not content.strip():
        error('file_text_empty', '文件没有可引用的正文。', 409, {fid:'empty_text'})
    return content, {'id':fid,'name':filename(file.get('name')),'parse_status':'ready',
                     'content_sha256':hashlib.sha256(content.encode()).hexdigest(),
                     'text_bytes':len(content.encode()),'chunk_count':len(chunks),
                     'usage':'user_reference','verified_source':False}
