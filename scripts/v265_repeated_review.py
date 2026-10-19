"""Six public cases, aligned crops and full scenes; rejections stay visible."""
import argparse
from pathlib import Path
import cv2
from PIL import Image, ImageDraw, ImageFont
from scripts.v265_transfer_matrix import pointset
from scripts.v265_matrix_sheets import review_crop


def run(a):
    cv2.setNumThreads(1)
    a.destination.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 17)
    for page, cases in enumerate([['case02', 'case05'], ['case04', 'case06'], ['case07', 'case08']], 1):
        sheet = Image.new('RGB', (1280, 1690), '#eeeeee')
        draw = ImageDraw.Draw(sheet)
        for row, case in enumerate(cases):
            for col, mode in enumerate(['source', 'A_baseline', 'I_ortho_jaw', 'K_ortho_silhouette']):
                x, y = col*320, row*845
                draw.text((x+6,y+7), case+' | '+mode, fill='black', font=font)
                path = a.fixtures/(case+'_source.jpg') if mode=='source' else a.output/case/(mode+'_selected.png')
                if not path.exists():
                    draw.text((x+12,y+170), 'REJECTED: folded field', fill='#990000', font=font)
                    draw.text((x+12,y+205), 'No output candidate', fill='#990000', font=font)
                    continue
                im = cv2.imread(str(path))
                _, _, points = pointset(im, a.models, col>0)
                crop, _ = review_crop(im, points)
                sheet.paste(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)), (x,y+35))
                context=Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
                context.thumbnail((310,385))
                sheet.paste(context, (x+(320-context.width)//2,y+442))
                draw.text((x+6,y+823), 'OFFLINE - NOT APPROVED', fill='#990000', font=font)
        sheet.save(a.destination/('repeated_review_'+str(page)+'.jpg'), quality=92)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--models',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fixtures',type=Path,default=Path('tests/fixtures/v265_matrix'))
    p.add_argument('--destination',type=Path,required=True)
    run(p.parse_args())
