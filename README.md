# Fecr içerik

Fecr uygulamasının ana sayfasındaki **Ayet**, **Hadis**, **Dua** ve **Özlü Sözler** düğmelerinin resimleri ile
Kütüphane rafındaki **kitaplar**. Uygulama bu klasörleri doğrudan buradan okur; eklemek veya silmek için uygulama güncellemesi gerekmez.

| Düğme | Klasör |
|---|---|
| Ayet | `Ayet/` |
| Hadis | `Hadis/` |
| Dua | `Dua/` |
| Özlü Sözler | `OzluSozler/` |
| Kütüphane kitapları | `Kitaplar/` |
| Helal Tarayıcı E-kodları | `Helal/` (`ekodlari.json`) |
| Kâri Tanı katalogları | `RecitID/` (`.shazamcatalog`) |

## Resim eklemek

1. github.com'da bu depoda ilgili klasörü açın.
2. **Add file → Upload files** ile resimleri sürükleyin (jpg, png, heic, webp, gif) ve **Commit changes** deyin.
3. Kullanıcılar uygulamada düğmeyi açtığında yeni resimleri görür (liste en geç birkaç dakika içinde yenilenir; aşağı çekince hemen yenilenir).

Resimler dosya adına göre sıralanır; sırayı belirlemek için `01-sabir.jpg`, `02-sukur.jpg` gibi numara verin.

## Kitap eklemek

`Kitaplar/` klasörüne PDF yükleyin. Rafta görünen ad dosya adıdır: baştaki `01-` gibi sıra numarası
gösterilmez, `-` ve `_` boşluk olur (`01-Riyazus_Salihin.pdf` → "Riyazus Salihin").
Kapak için aynı adlı bir resim yükleyin (`01-Riyazus_Salihin.jpg`); yoksa kapak uygulamada çizilir.
Kitap kullanıcının telefonuna ilk açılışta iner, sonra internetsiz okunur. GitHub'ın web yüklemesinde
dosya başına 25 MB sınırı vardır; daha büyük PDF'leri sıkıştırın ya da `git` ile yükleyin (100 MB'a kadar).

## Kâri Tanı katalogları

`RecitID/` klasöründe her kâri için bir ShazamKit kataloğu (`.shazamcatalog`) vardır. Kataloglarda ses yoktur,
yalnızca ayet kayıtlarından çıkarılmış ses imzaları vardır; uygulama dinlediği tilaveti telefonda bunlarla eşleştirir.
Kayıtlar Islamic Network'ün açık ses arşivindendir ([alquran.cloud](https://alquran.cloud/terms-and-conditions):
kârilerden ücretsiz, ticari olmayan yeniden dağıtım için lisanslı). Kataloglar Fecr deposundaki
`Tools/build_recit_catalog.swift` ile üretilir:

    swift Tools/build_recit_catalog.swift alafasy.shazamcatalog "ar.alafasy/128=Mişari el-Afasi"

## Resim veya kitap silmek

Dosyayı açıp çöp kutusu simgesiyle silin ve commit edin. Uygulama bir sonraki yenilemede kaldırır.

Bu depo herkese açıktır; yalnızca paylaşma hakkınız olan resimleri ekleyin.
