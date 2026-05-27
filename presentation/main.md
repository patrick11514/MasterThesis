---
theme: gaia
_class: lead
paginate: true
backgroundColor: #fff
marp: true
title: 'Klasifikace astronomických fotografií - Patrik Mintěl'
author: 'Patrik Mintěl'
language: cs
---

<style>
  /*!
  Theme: GitHub Dark Dimmed
  Description: Dark dimmed theme as seen on github.com
  Author: github.com
  Maintainer: @Hirse
  Updated: 2021-05-15

  Colors taken from GitHub's CSS
*/

.hljs {
  color: #adbac7;
  background: #22272e;
}

.hljs-doctag,
.hljs-keyword,
.hljs-meta .hljs-keyword,
.hljs-template-tag,
.hljs-template-variable,
.hljs-type,
.hljs-variable.language_ {
  /* prettylights-syntax-keyword */
  color: #f47067;
}

.hljs-title,
.hljs-title.class_,
.hljs-title.class_.inherited__,
.hljs-title.function_ {
  /* prettylights-syntax-entity */
  color: #dcbdfb;
}

.hljs-attr,
.hljs-attribute,
.hljs-literal,
.hljs-meta,
.hljs-number,
.hljs-operator,
.hljs-variable,
.hljs-selector-attr,
.hljs-selector-class,
.hljs-selector-id {
  /* prettylights-syntax-constant */
  color: #6cb6ff;
}

.hljs-regexp,
.hljs-string,
.hljs-meta .hljs-string {
  /* prettylights-syntax-string */
  color: #96d0ff;
}

.hljs-built_in,
.hljs-symbol {
  /* prettylights-syntax-variable */
  color: #f69d50;
}

.hljs-comment,
.hljs-code,
.hljs-formula {
  /* prettylights-syntax-comment */
  color: #768390;
}

.hljs-name,
.hljs-quote,
.hljs-selector-tag,
.hljs-selector-pseudo {
  /* prettylights-syntax-entity-tag */
  color: #8ddb8c;
}

.hljs-subst {
  /* prettylights-syntax-storage-modifier-import */
  color: #adbac7;
}

.hljs-section {
  /* prettylights-syntax-markup-heading */
  color: #316dca;
  font-weight: bold;
}

.hljs-bullet {
  /* prettylights-syntax-markup-list */
  color: #eac55f;
}

.hljs-emphasis {
  /* prettylights-syntax-markup-italic */
  color: #adbac7;
  font-style: italic;
}

.hljs-strong {
  /* prettylights-syntax-markup-bold */
  color: #adbac7;
  font-weight: bold;
}

.hljs-addition {
  /* prettylights-syntax-markup-inserted */
  color: #b4f1b4;
  background-color: #1b4721;
}

.hljs-deletion {
  /* prettylights-syntax-markup-deleted */
  color: #ffd8d3;
  background-color: #78191b;
}

.hljs-char.escape_,
.hljs-link,
.hljs-params,
.hljs-property,
.hljs-punctuation,
.hljs-tag {
  /* purposely ignored */
}

/*MY STYLE*/

h1, h2, strong {
  color: #F96743 !important;
}

img[alt~="center"] {
  display: block;
  margin: 0 auto;
}
</style>

# Klasifikace astronomických fotografií

**<span style="color:#101417;">Patrik Mintěl</span>**

Semestrální Projekt - VŠB-TUO
Vedoucí práce: Ing. Jan Gaura, Ph.D.

---

# Motivace a pořizovací technika

- Problém: snímání objektů hlubokého vesmíru vyžaduje dlouhé expozice a stovky až tisíce snímků
- Surová data: data z kamer jsou uložena bez komprese či úprav
- Šum: užitečná data jsou skryta hluboko v šumu
- Lidský faktor: manuální kontrola snímků a vyřazování těch znehodnocených mraky, vadou, je časově náročné a chybové

---

<div style="display: flex; justify-content: center; gap: 1rem">
    <img src="./PXL_20260515_175119231~2.jpg" width="400">
    <img src="./IMG_20260526_025716.jpg" width="400">
</div>
<sopan style="text-align: center;">
ZWO ASI 585MC Pro - 4k Sony IMX585 CMOS senzor
</span>

---

# Datový formát FITS

![center width:550px](https://upload.patrick115.eu/raw/images/ee8b02f4-611c-4e06-98f3-9190a2431bfc.png)

---

# Tech stack

- Tauri
  - Framework kombinující Rust + Webové technologie
  - Výhody: rychlost (Rust) + jednoduché UI (HTML/CSS/JS)

- Rust
- Svelte (frontend)

---

![center width:1120px](https://upload.patrick115.eu/raw/images/2b42a86d-b215-4c1e-984b-c872cba85f0d.png)

---

# Import dat

![bg right width:500px](https://upload.patrick115.eu/raw/images/0d848f04-9602-49c2-8ecf-f2012e4c27cf.png)

- Podpora pro FITS formát
- Soubory jsou rozděleny podle absolutní cesty pomocí pravidel
- Prefix + Suffix
- /drive/Object M45/Session 2026-01-15/Light/....fits

---

# Seskupení dat

![](https://upload.patrick115.eu/raw/images/1d96f4e7-b29d-476b-9b4b-7fd32903a888.png)

---

# Typy snímků

- Light: hlavní snímek s objektem
- Dark: snímek bez světla, zachycuje šum senzoru (musí sedět teplota, gain, expozice)
- Flat: snímek s rovnoměrným osvětlením, zachyzuje vinětaci a prach (musí být pořízena ideálně před/po noci)
- Bias: snímek s "nulovou" expozicí, zachycuje čtecí šum senzoru (musí gain)

- Master snímek: průměr z více snímků stejného typu
  - Tvořen skládáním (stackováním) jednotlivých snímků

---

# Kalibrace světelných snímků

- Tvorba master snímků pro Dark, Flat a Bias
- Master Dark: Sigma Clipped Mean (Welfordův algoritmus)
- Master Flat + Master Bias: průměr

- Kalibrační rovnice pro každý pixel:

$$ Calibrated = \frac{Light - MasterDark}{MasterFlat} $$

---

# Metriky

- Knihovna SEP - Source Extraction and Photometry
- Metriky pro každý snímek:

![width:1200px](https://upload.patrick115.eu/raw/images/a81a50c4-7a52-4715-8b3d-74d3bba5ef57.png)

---

# Ověření a výsledky

- Dataset: Mlhovina Rozeta, celkem 1104 snímků + kalibrační data
- Výsledný čas zpracování 32 minut
  - 30 minut - kalibrace
  - 2 minuty - metriky
- Většinu času CPU spalo, čekalo na I/O operace (bottleneck)
- Paralelizace pomocí Rayon (Rust)
- každá operace: načíst obrázek -> zpracovat -> uložit

---

# Analyza výsledků

- Perfektně: kompletní mraky, rozmazání hvězd, nebo snímky bez hvězd
- Špatně: tenký mrak
  ![center width:1024px](https://upload.patrick115.eu/raw/images/90ec1245-150e-43ee-b4dc-6b4bcda0d43e.png)

---

# Závěr

- V nadměrném množství korektně klasifikuje snímek
- Nevýhoda: nutnost úpravy konstant pro klasifikaci podle dat
- Řešení: CNN pro klasifikaci snímků, bez nutnosti nastavovat konstanty
- Bude rozvinuto v rámci Diplomové práce
- Aktuální aplikace bude použita pro klasifikaci snímků pro vlastní NN dataset

---

![bg](https://patrick115.eu/image/e24d15a109be1d659dc561308bd6b93c.png?format=jpg&quality=75)
