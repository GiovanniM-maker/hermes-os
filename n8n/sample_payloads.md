# Size_Comparator — sample webhook payloads

6 prodotti reali estratti dal foglio `FULL_CATALOG_6BRANDS_2026`, pronti da
iniettare nel payload del webhook come `target_product`. Servono per simulare
il caso "utente sulla pagina prodotto X": il sito sa già brand, tipo, URL e
tabella taglie → li passa al bot e il bot NON deve andare a cercarli nel DB.

Endpoint: `POST https://giovannimavilla.app.n8n.cloud/webhook/size-recommend`

Forma del payload:
```json
{
  "user_message": "Ho una Nike M oversize",
  "target_product": {
    "brand": "<brand>",
    "name":  "<nome del prodotto>",
    "product_url": "<url>",
    "product_group": "tops|bottoms",
    "product_type":  "<shirt|hoodie|skirt|...>",
    "sizes": [
      { "size_label": "M", "chest": 96, "shoulder": 44, "sleeve": 62, "height": 70 },
      { "size_label": "L", "chest": 102, ...  },
      ...
    ]
  }
}
```

Se passi `target_product.sizes`, il bot NON fa lookup nel foglio per il
prodotto target — usa quelle misure direttamente. Resta il lookup sul foglio
solo per il **reference** (il capo che l'utente già possiede).

In alternativa puoi ancora passare solo `target_product_url` e il bot cercherà
le righe nel foglio (comportamento v1).

---

## Product 1 — OVS — Blusa LES COPAINS (tops / shirt)

```json
{
  "user_message": "Ho una M di Mango che mi sta bene",
  "target_product": {
    "brand": "OVS",
    "name": "Blusa senza maniche in puro cotone blu regular fit LES COPAINS da Donna",
    "product_url": "https://www.ovs.it/it/it/p/blusa-senza-maniche-in-puro-cotone-blu-regular-fit-002575265.html",
    "product_group": "tops",
    "product_type": "shirt",
    "sizes": [
      { "size_label": "XS", "chest": 84 },
      { "size_label": "S",  "chest": 89 },
      { "size_label": "M",  "chest": 94 },
      { "size_label": "L",  "chest": 99 },
      { "size_label": "XL", "chest": 105 },
      { "size_label": "38", "chest": 83 },
      { "size_label": "40", "chest": 87 },
      { "size_label": "42", "chest": 91 },
      { "size_label": "44", "chest": 95 },
      { "size_label": "46", "chest": 99 },
      { "size_label": "48", "chest": 103 },
      { "size_label": "50", "chest": 107 },
      { "size_label": "52", "chest": 111 }
    ]
  }
}
```

## Product 2 — Bonprix — Abito a fascia (tops / top)

```json
{
  "user_message": "Ho una felpa OVS L che mi sta bene",
  "target_product": {
    "brand": "Bonprix",
    "name": "Abito a fascia in maglia a costine",
    "product_url": "https://www.bonprix.it/prodotto/abito-a-fascia-in-maglia-a-costine-nero-bianco-a-righe-933114/",
    "product_group": "tops",
    "product_type": "top",
    "sizes": [
      { "size_label": "38", "chest": 75.5 },
      { "size_label": "40", "chest": 79.5 },
      { "size_label": "42", "chest": 83.5 },
      { "size_label": "44", "chest": 87.5 },
      { "size_label": "46", "chest": 91.5 },
      { "size_label": "48", "chest": 95.5 },
      { "size_label": "50", "chest": 100 },
      { "size_label": "52", "chest": 105 },
      { "size_label": "54", "chest": 110.5 },
      { "size_label": "56", "chest": 116.5 }
    ]
  }
}
```

## Product 3 — Mango — Blusa asimmetrica satinata (tops / shirt)

```json
{
  "user_message": "Ho una OVS 44 camicia",
  "target_product": {
    "brand": "Mango",
    "name": "Blusa asimmetrica satinata",
    "product_url": "https://shop.mango.com/it/it/p/donna/camicie-e-bluse/bluse/blusa-asimmetrica-satinata_27069059",
    "product_group": "tops",
    "product_type": "shirt",
    "sizes": [
      { "size_label": "XXS", "chest": 78 },
      { "size_label": "XS",  "chest": 82 },
      { "size_label": "S",   "chest": 86 },
      { "size_label": "M",   "chest": 92 },
      { "size_label": "L",   "chest": 98 },
      { "size_label": "XL",  "chest": 104 },
      { "size_label": "XXL", "chest": 110 }
    ]
  }
}
```

## Product 4 — Armani — Bermuda twill (bottoms / shorts)

```json
{
  "user_message": "Ho una Mango 42 pantaloni",
  "target_product": {
    "brand": "Armani",
    "name": "Bermuda con coulisse in twill di cotone",
    "product_url": "https://www.armani.com/it-it/armani-exchange/bermuda-con-coulisse-in-twill-di-cotone-cod-XM002741-AF23202-U6229/",
    "product_group": "bottoms",
    "product_type": "shorts",
    "sizes": [
      { "size_label": "26", "waist": 66.5, "hip": 87 },
      { "size_label": "27", "waist": 70,   "hip": 89 },
      { "size_label": "28", "waist": 72,   "hip": 91 },
      { "size_label": "29", "waist": 74,   "hip": 93 },
      { "size_label": "30", "waist": 76,   "hip": 96 },
      { "size_label": "32", "waist": 80,   "hip": 100 },
      { "size_label": "34", "waist": 86,   "hip": 104 },
      { "size_label": "36", "waist": 90,   "hip": 108 }
    ]
  }
}
```

## Product 5 — Mango — Gonna crochet (bottoms / skirt)

```json
{
  "user_message": "Ho una OVS S gonna",
  "target_product": {
    "brand": "Mango",
    "name": "Gonna crochet ricamata con fiori",
    "product_url": "https://shop.mango.com/it/it/p/donna/gonne/corte/gonna-crochet-ricamata-con-fiori_27099057",
    "product_group": "bottoms",
    "product_type": "skirt",
    "sizes": [
      { "size_label": "XXS", "waist": 59, "hip": 86 },
      { "size_label": "XS",  "waist": 62, "hip": 90 },
      { "size_label": "S",   "waist": 66, "hip": 94 },
      { "size_label": "M",   "waist": 72, "hip": 100 },
      { "size_label": "L",   "waist": 78, "hip": 106 },
      { "size_label": "XL",  "waist": 85, "hip": 112 },
      { "size_label": "XXL", "waist": 92, "hip": 118 }
    ]
  }
}
```

## Product 6 — OVS — Gonna LES COPAINS (bottoms / skirt)

```json
{
  "user_message": "Ho una Mango 42 gonna",
  "target_product": {
    "brand": "OVS",
    "name": "Gonna beige lunga in puro cotone LES COPAINS da Donna",
    "product_url": "https://www.ovs.it/it/it/p/gonna-beige-lunga-in-puro-cotone-002559139.html",
    "product_group": "bottoms",
    "product_type": "skirt",
    "sizes": [
      { "size_label": "38", "waist": 63, "hip": 89 },
      { "size_label": "40", "waist": 67, "hip": 93 },
      { "size_label": "42", "waist": 71, "hip": 97 },
      { "size_label": "44", "waist": 75, "hip": 101 },
      { "size_label": "46", "waist": 79, "hip": 105 },
      { "size_label": "48", "waist": 83, "hip": 109 },
      { "size_label": "50", "waist": 87, "hip": 113 },
      { "size_label": "52", "waist": 91, "hip": 117 }
    ]
  }
}
```
