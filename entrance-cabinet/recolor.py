import numpy as np, sys
from PIL import Image, ImageDraw, ImageFilter
SRC='/Users/home/Downloads/כניסה - הבית החדש/07 - הדמיית ארון הכניסה.png'
def build_mask(src):
    a=np.asarray(src).astype(np.float32)/255
    h,w=a.shape[:2]
    def polym(pts,grow=0):
        im=Image.new('L',(w,h),0); ImageDraw.Draw(im).polygon(pts,fill=255)
        for _ in range(grow): im=im.filter(ImageFilter.MaxFilter(3))
        return np.asarray(im)>0
    pts=[(147,298),(529,160),(531,745),(147,625)]
    P_in=polym(pts,grow=-0) ; P_out=polym(pts,grow=9)
    mx=a.max(2); mn=a.min(2); d=mx-mn
    s=np.where(mx>0,d/np.maximum(mx,1e-6),0)
    r,g,b=a[...,0],a[...,1],a[...,2]
    hue=np.zeros_like(mx); m=d>1e-6
    rr=(mx==r)&m; gg=(mx==g)&m&~rr; bb=(mx==b)&m&~rr&~gg
    hue[rr]=((g-b)[rr]/d[rr])%6; hue[gg]=((b-r)[gg]/d[gg])+2; hue[bb]=((r-g)[bb]/d[bb])+4
    hue*=60
    doorlike=(hue>=40)&(hue<=105)&(s>0.04)&(s<0.40)&(mx>0.10)&(mx<0.95)
    copper=((hue<40)|(hue>330))&(s>0.22)
    cm=Image.fromarray((copper*255).astype('uint8')).filter(ImageFilter.MaxFilter(3))
    copper=np.asarray(cm)>0
    P_core=polym([(153,303),(523,170),(525,737),(153,618)])
    M=((P_out&doorlike)|P_core)&~copper
    m=Image.fromarray((M*255).astype('uint8'))
    m=m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    return np.asarray(m).astype(np.float32)/255, a
def to_lin(x): return np.where(x<=0.04045,x/12.92,((x+0.055)/1.055)**2.4)
def to_srgb(x): return np.where(x<=0.0031308,x*12.92,1.055*np.power(np.clip(x,0,None),1/2.4)-0.055)
def recolor(hexcode,out):
    src=Image.open(SRC).convert('RGB')
    M,a=build_mask(src)
    lin=to_lin(a)
    Y=0.2126*lin[...,0]+0.7152*lin[...,1]+0.0722*lin[...,2]
    sel=M>0.5
    ymean=np.median(Y[sel])
    f=np.clip(Y/ymean,0.35,1.45)*0.96
    t=np.array([int(hexcode[i:i+2],16)/255 for i in (0,2,4)],dtype=np.float32)
    tl=to_lin(t)
    new=np.clip(tl[None,None,:]*f[...,None],0,1)
    # soft shoulder so highlights on light colours do not clip flat
    new=new/(1+0.0*new)
    outlin=lin*(1-M[...,None])+new*M[...,None]
    res=(np.clip(to_srgb(outlin),0,1)*255).astype('uint8')
    im=Image.fromarray(res).resize((src.width*3,src.height*3),Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2,percent=120,threshold=2))
    im.save(out,quality=90); print(out,im.size,'ymean',round(float(ymean),4))
if __name__=='__main__':
    recolor(sys.argv[1],sys.argv[2])
