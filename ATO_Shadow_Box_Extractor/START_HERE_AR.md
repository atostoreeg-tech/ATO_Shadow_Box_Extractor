# ATO Shadow Box Extractor — ابدأ من هنا

ده مشروع **موقع ويب شغال** للمعالجة الموجَّهة للـ Shadow Box. الـ Frontend والـ Backend وكل ملفات التشغيل والنشر موجودة في نفس المشروع. مش محتاج تربط Next.js أو Firebase علشان تبدأ.

## الملفات اللي الموقع بيطلعها

- `Background.png` — الخلفية بعد تصحيح المنظور وإزالة المناطق اللي علمت عليها بعلامة اللوجو. إزالة العناصر بتستخدم OpenCV Inpainting وبتخمّن الجزء المغطى، ومش بتسترجع التفاصيل الحقيقية بشكل مضمون.
- `Logo.dxf` — DXF حقيقي بـclosed LWPOLYLINE و3 Layers: OUTER_CONTOURS / INTERNAL_CUTOUTS / ENGRAVE_DETAILS، والوحدات mm.
- `Logo.svg` — معاينة Vector حقيقية، فيها الـ cutouts على شكل فراغات.
- `ATO_Exports.zip` — كل الملفات السابقة ومعاهم تقرير فني.

## الاستخدام من واجهة الموقع

1. ارفع صورة Shadow Box.
2. ظبّط النقط الصفراء الـ4 على **أركان التصميم المطبوع من الداخل**، مش الفريم.
3. اختار `Auto Select ROI` واسحب مستطيل على اللوجو. الأداة هترشح لك منطقة، وبعدها استخدم `Paint Logo` لتكملة أي جزء، و`Erase Logo` لمسح المساحات الزيادة أو عمل الفتحات الداخلية. للأجزاء المحفورة استخدم `Engrave`.
4. اكتب **العرض الحقيقي للتصميم بالمليمتر** في `Measured artwork width`. مثال 240mm لو أنت قايِسه. البرنامج مش بيخمّن مقاسات.
5. اختار 300 DPI واضغط `Generate production files`.
6. راجع المعاينة، وبعدها نزّل PNG وDXF وSVG أو الـ ZIP.

**مهم:** التفاصيل المخفية ورا اللوجو والكتابة الصغيرة مش مضمونة في الصورة الناتجة. وملف DXF ده 2D outlines، مش ملف STL جاهز ولا بيحدد ارتفاع الـ3D. لازم تشوف الفتحات والأبعاد في برنامج CAD قبل التصنيع.

## تجربة على Windows

ثبت Python 3.11، افتح PowerShell جوه فولدر المشروع، وشغّل:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --port 8000
```

افتح: <http://127.0.0.1:8000>

## نشر الموقع Online على Render

1. اعمل Repository **Private** على GitHub وارفع محتويات الفولدر كامل.
2. افتح <https://render.com> وبعدها **New → Web Service** واربط الـRepository.
3. اختار **Docker**، ويفضّل خطة `1c-2g` (2GB RAM) للصور الكبيرة؛ الخطة `0.5c-512mb` أرخص لكن قد لا تتحمل الصور الكبيرة. ملف `render.yaml` موجود للنشر بنظام Blueprint.
4. من Environment ضيف متغير `ATO_ACCESS_KEY` واكتب كلمة سر طويلة قوية. بلاش تحطها في GitHub أو في كود الـFrontend.
5. Health Check Path: `/api/health`، وبعد الـDeploy افتح رابط `onrender.com` اللي Render هيديهولك.
6. هتلاقي خانة لكلمة السر في الموقع: اكتب نفس `ATO_ACCESS_KEY` علشان تسمح بالمعالجة.

**ملاحظات الاستضافة:** النتائج متاحة لمدة ساعة تقريبًا وممكن تتمسح قبل كده مع إعادة تشغيل الخدمة؛ نزّل ملفاتك فورًا. الرابط الموقت الخاص بالنتائج مش عليه Login مستقل. مشروع الـMVP مناسب لتجارب فريق صغير ومش نظام SaaS آمن بالكامل لعشرات العملاء من غير مصادقة حقيقية، Rate Limits، طابور مهام وتخزين خارجي.

## حالة الإنجاز

- واجهة فعلية لرفع الصور ورسم Mask وتعديل الأربع زوايا.
- FastAPI endpoints وOpenCV + DXF/SVG vector export.
- اختبارات Backend تلقائية (تشغيلها `python -m pytest -q`).
- Dockerfile + render.yaml جاهزين للنشر.
- **مش منشور Live لسه**؛ رابط التشغيل العام محتاج رفع المشروع على حساب GitHub وRender الخاصين بيك.

اقرأ `README.md` لو محتاج تفاصيل API وحدود الأمان والتطوير للنسخة الثانية.
