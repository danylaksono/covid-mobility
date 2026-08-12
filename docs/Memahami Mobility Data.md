---
title: "Memahami Mobility Data"
source: "https://ugm365.sharepoint.com/sites/OpenMobilityData/SitePages/Asal-Usul-Data.aspx"
author:
published:
created: 2026-08-12
description:
tags:
  - "clippings"
---
![](https://media.akamai.odsp.cdn.office.net/southeastasia1-mediap.svc.ms/transform/thumbnail?provider=url&inputFormat=jpg&docid=https%3A%2F%2Fcdn.hubblecontent.osi.office.net%2Fm365content%2Fpublish%2Fb5dce3b7-5545-4721-b7e1-1dcc8f05e97b%2Fimage.jpg&w=1600 "Memahami Mobility Data")

Widyawan

## Data

Data pergerakan (*mobility*) termasuk jenis SIGINT (*signal intelligence*), memerlukan mekanisme khusus untuk memperolehnya. Berbeda dengan OSINT (*open source intelligence*) seperti data berita atau sosial media.

Data berisikan **identifikasi, latitute, longitude** dan ***timestamp**.* Identifikasi (ID) smartphone android berasal dari MAID ([*Mobile Advertising Identifier*)](https://support.google.com/googleplay/android-developer/answer/6048248?hl=en) atau Ad Id (*Advertising Identifier*). Untuk smartphone IOS dinamakan IFDA (Identifier for Advertisers or IDFA). Terdiri dari 32 hyphen-separated karakter, contoh: 3f097372-f01e-4b64-984c-395ae5828ee6. Untuk menjaga privasi, data identifikasi tersebut dianonimkan.

Contoh dalam perangkat android bisa dilihat pada [Gambar 1](https://martech.org/google-replacing-android-id-with-advertising-id-similar-to-apples-idfa/)

Gambar 1. MAID pada Android

Data latitude dan longitude diperoleh dari app dalam *smartphone* yang mengirimkan posisi GPS, ketika terdapat update, kepada aggregator. Update app termasuk ketika diaktifkan atau melakukan transaksi. Kategori app yang menggunakan fitur MAID bisa dilihat pada Gambar 2.

![]()

Gambar 2. App kategori \[1\]

## Perolehan dan Penggunaan

Data yang dibagi merupakan data pergerakan (*mobility*) yang mencakup wilayah DIY (Daerah Istimewa Yogyakarta) dari Oktober 2021 - Mei 2022. Data diperoleh dari agregator untuk keperluan pembelajaran dan penelitian yang dilakukan oleh civitas UGM.

Penelitian mengenai pola pergerakan manusia, maupun penerapan dalam berbagai bidang seperti transportasi, pariwisata, perencanaan kota bisa dilakukan memanfaatkan data tersebut. Selain keperluan penelitian, pembelajaran di kelas maupun praktikum berbasis informasi spasial juga dimungkinkan.

## Privasi

Agregator mengumpulkan semua data yang sepenuhnya dianonimkan. Publisher dari smartphone app menggunakan beberapa platform untuk memperoleh ijin dari pengguna (*user* *consent*) dan juga menyediakan mekanisme *opt-out* (penolakan).

\[1\] Digipop Research Platform, MD Media, unpublished