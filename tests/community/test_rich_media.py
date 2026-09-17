from io import BytesIO
import uuid

import pytest
from PIL import Image
from sqlalchemy import select

from community.extensions import db
from community.models import Post, ImageAsset, PostRevision
from .conftest import register, token
from .test_posts import send, publish, JSON


def image_bytes():
    output = BytesIO(); Image.new('RGB', (64, 48), '#175c4b').save(output, 'PNG')
    return output.getvalue()


def upload(client, data=None, filename='sample.png'):
    return client.post('/images', data={'file': (BytesIO(data if data is not None else image_bytes()), filename)},
        headers={'X-CSRFToken': token(client), **JSON})


def document(image=None, color='#b42318'):
    children = [{'type':'paragraph', 'content':[{'type':'text','text':'有颜色的笔记',
        'marks':[{'type':'textStyle','attrs':{'color':color,'backgroundColor':'#fff3bf','fontSize':'24px'}}]}]}]
    if image: children.append({'type':'image','attrs':{'src':image,'alt':'示例图片','displayWidth':'50'}})
    return {'type':'doc','content':children}


def save(client, rich, post=None):
    data = {'title':'富文本帖子', 'rich_content':rich, 'operation_key':uuid.uuid4().hex}
    if post: data['base_version'] = post['version']
    return send(client, 'PATCH' if post else 'POST', f"/posts/{post['id']}" if post else '/posts', data)


def test_rich_text_color_and_picture_survive_revision_publish(app, client):
    register(client)
    image = upload(client)
    assert image.status_code == 201
    src = image.json['url']
    rich = document(src)
    draft = save(client, rich)
    assert draft.status_code == 201, draft.json
    p = draft.json
    shown = client.get(f"/posts/{p['id']}")
    assert 'rt-fg-red' in shown.text and 'rt-bg-yellow' in shown.text and 'rt-size-24' in shown.text
    assert src in shown.text and 'rt-image-50' in shown.text
    assert client.get(src).headers['Content-Type'].startswith('image/webp')
    guest = app.test_client()
    assert guest.get(src).status_code == 404
    other = app.test_client(); register(other, 'bob')
    assert other.get(src).status_code == 404
    assert save(other, rich).status_code == 404
    public = publish(client, p).json
    assert guest.get(src).status_code == 200
    assert guest.get(src).headers['Cache-Control'] == 'no-store'
    edited = save(client, document(color='#175cd3'), public).json
    assert guest.get(src).status_code == 404  # historical references do not make it public
    history = client.get(f"/posts/{p['id']}/revisions", headers=JSON).json['revisions']
    assert history[0]['rich_content']['content'][0]['content'][0]['marks'][0]['attrs']['color'] == '#175cd3'
    assert history[-1]['rich_content']['content'][1]['attrs']['src'] == src
    assert 'rt-fg-red' in client.get(f"/posts/{p['id']}/revisions").text
    assert client.get(src).status_code == 200  # owner can review historical image
    restored = save(client, rich, edited).json
    assert guest.get(src).status_code == 200
    send(client, 'DELETE', f"/posts/{p['id']}", {'base_version':restored['version'],'operation_key':uuid.uuid4().hex})
    assert guest.get(src).status_code == 404


def test_image_hidden_status_and_cross_owner_adoption(app, client):
    register(client)
    src = upload(client).json['url']
    p = publish(client, save(client, document(src)).json).json
    other = app.test_client(); register(other, 'bob')
    assert other.get(src).status_code == 200
    assert save(other, document(src)).status_code == 404
    with app.app_context():
        db.session.get(Post, p['id']).status = 'hidden'; db.session.commit()
    assert other.get(src).status_code == 404


@pytest.mark.parametrize('raw,name', [(b'<svg onload="alert(1)"></svg>','evil.png'), (b'not an image','a.jpg'), (b'a'*(5*1024*1024+1),'large.png')], ids=['svg', 'invalid', 'oversize'])
def test_invalid_upload(client, raw, name):
    register(client)
    assert upload(client, raw, name).status_code in (400,413)


def test_upload_requires_login_csrf_and_reencodes(app, client):
    assert upload(client).status_code == 401
    register(client)
    assert client.post('/images',data={'file':(BytesIO(image_bytes()),'a.png')}).status_code == 400
    r = upload(client, image_bytes()+b'PRIVATE_TRAILING_MARKER', '../../x.png')
    assert r.status_code == 201
    response = client.get(r.json['url'])
    assert b'PRIVATE_TRAILING_MARKER' not in response.data
    assert response.data[:4] == b'RIFF'
    with app.app_context():
        assert db.session.scalar(select(ImageAsset)).owner_id == client.get('/auth/me').json['id']


@pytest.mark.parametrize('bad', [
    {'type':'doc','content':[{'type':'image','attrs':{'src':'https://example.com/a.png'}}]},
    {'type':'doc','content':[{'type':'text','text':'bad'}]},
    document(color='red; background:url(https://example.com)'),
    {'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'x','marks':[{'type':'link','attrs':{'href':'javascript:alert(1)'}}]}]}]},
    {'type':'doc','content':[{'type':'script','content':[]}]},
])
def test_reject_unsafe_rich_nodes(client,bad):
    register(client)
    assert save(client,bad).status_code == 400


def test_html_text_is_escaped_and_lossy_edit_is_rejected(client):
    register(client)
    rich = {'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'<img src=x onerror=alert(1)>'}]}]}
    p = save(client,rich).json
    html = client.get(f"/posts/{p['id']}").text
    assert '&lt;img' in html and '<img src=x' not in html
    response = send(client,'PATCH',f"/posts/{p['id']}",{'title':'lost','markdown':'lost','base_version':1,'operation_key':uuid.uuid4().hex})
    assert response.status_code == 400


def test_image_only_post_and_limits(client):
    register(client)
    src = upload(client).json['url']
    rich = {'type':'doc','content':[{'type':'image','attrs':{'src':src}}]}
    assert save(client,rich).status_code == 201
    assert save(client,{'type':'doc','content':rich['content'] * 13}).status_code == 400
    assert save(client,{'type':'doc','content':[]}).status_code == 400
    assert save(client,{'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'中'*30001}]}]}).status_code == 400
