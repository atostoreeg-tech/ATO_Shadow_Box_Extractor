import io
import json
import zipfile
from pathlib import Path

import cv2
import ezdxf
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.processing import (image_corners, make_contours, produce, read_alpha_mask,
                            read_rgb, sort_clockwise_tl)


def fixture():
    width,height=520,360
    yy,xx=np.mgrid[:height,:width]
    art=np.zeros((height,width,3),dtype=np.uint8)
    art[:,:,0]=(45+xx*0.2).astype(np.uint8)
    art[:,:,1]=(70+yy*0.2).astype(np.uint8)
    art[:,:,2]=130
    # Logo is a raised ring of one color, with a genuine transparent hole.
    mask=np.zeros((height,width),dtype=np.uint8)
    cv2.circle(mask,(255,180),65,255,-1)
    cv2.circle(mask,(255,180),20,0,-1)
    image=art.copy();image[mask>0]=(235,235,235)
    engrave=np.zeros_like(mask)
    cv2.rectangle(engrave,(225,148),(235,161),255,-1)
    corners=[[0,0],[width-1,0],[width-1,height-1],[0,height-1]]
    return image,mask,engrave,corners


def png_mask(mask):
    rgba=np.zeros((*mask.shape,4),dtype=np.uint8)
    rgba[:,:,:3]=255;rgba[:,:,3]=mask
    f=io.BytesIO();Image.fromarray(rgba).save(f,format='PNG')
    return f.getvalue()


def png_image(image):
    f=io.BytesIO();Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB)).save(f,format='PNG')
    return f.getvalue()


def test_sort_corners():
    src=np.array([[100,300],[0,0],[100,0],[0,300]],np.float32)
    actual=sort_clockwise_tl(src).tolist()
    assert actual == [[0,0],[100,0],[100,300],[0,300]]


def test_processing_dxf_svg_and_png():
    image,mask,engrave,corners=fixture()
    outputs,report=produce(image,mask,engrave,corners,artwork_width_mm=220,
                           dpi=150,simplify_px=.6)
    assert {'Background.png','Logo.dxf','Logo.svg','Processing_Report.json'} == set(outputs)
    assert report['contour_counts']['OUTER_CONTOURS']>=1
    assert report['contour_counts']['INTERNAL_CUTOUTS']>=1
    assert report['contour_counts']['ENGRAVE_DETAILS']>=1
    assert b'fill-rule="evenodd"' in outputs['Logo.svg']
    with Image.open(io.BytesIO(outputs['Background.png'])) as im:
        assert im.size[0] == round(220/25.4*150)
        assert abs(im.info['dpi'][0]-150)<1
        # Raised white ring must be estimated away, not retained as solid white.
        bg=np.array(im)
        assert np.mean(bg[bg.shape[0]//2,bg.shape[1]//2 + 250]) < 200
    doc=ezdxf.read(io.StringIO(outputs['Logo.dxf'].decode()))
    assert doc.header['$INSUNITS']==4
    lines=list(doc.modelspace().query('LWPOLYLINE'))
    assert lines and all(line.closed for line in lines)
    layers={line.dxf.layer for line in lines}
    assert layers == {'OUTER_CONTOURS','INTERNAL_CUTOUTS','ENGRAVE_DETAILS'}
    assert all(len(line)>=3 for line in lines)


def test_api_process_and_individual_download(tmp_path,monkeypatch):
    from app import main
    monkeypatch.setattr(main,'JOB_DIR',tmp_path)
    img,mask,eng,corners=fixture()
    client=TestClient(app)
    assert client.get('/api/health').json()['status']=='ok'
    response=client.post('/api/process',data={
        'corners_json':json.dumps(corners),'artwork_width_mm':'220','dpi':'150'},files={
        'image':('source.png',png_image(img),'image/png'),
        'logo_mask':('mask.png',png_mask(mask),'image/png'),
        'engrave_mask':('engrave.png',png_mask(eng),'image/png'),
    })
    assert response.status_code==200, response.text
    result=response.json()
    for item in ['Background.png','Logo.dxf','Logo.svg','ATO_Exports.zip']:
        downloaded=client.get(result['files'][item])
        assert downloaded.status_code==200
        assert len(downloaded.content)>100
    zipped=client.get(result['files']['ATO_Exports.zip']).content
    with zipfile.ZipFile(io.BytesIO(zipped)) as z:
        assert {'Background.png','Logo.dxf','Logo.svg','Processing_Report.json'}==set(z.namelist())
    assert client.get('/').status_code==200


def test_error_missing_mask(tmp_path,monkeypatch):
    from app import main
    monkeypatch.setattr(main,'JOB_DIR',tmp_path)
    img,mask,eng,corners=fixture()
    mask[:]=0
    client=TestClient(app)
    response=client.post('/api/process',data={
        'corners_json':json.dumps(corners),'artwork_width_mm':'220'},files={
        'image':('source.png',png_image(img),'image/png'),
        'logo_mask':('mask.png',png_mask(mask),'image/png'),
        'engrave_mask':('engrave.png',png_mask(eng),'image/png'),
    })
    assert response.status_code==422
    assert 'logo' in response.json()['detail'].lower()


def test_access_key_required(monkeypatch):
    monkeypatch.setenv('ATO_ACCESS_KEY','test-secret')
    with TestClient(app) as client:
        response=client.post('/api/corners',files={'image':('x.png',b'fake','image/png')})
        assert response.status_code==401
