# Size Comparator — Frontend Integration Spec

Questo documento descrive i 6 prodotti, il contratto del webhook n8n e il flusso che il front-end deve implementare.

## 1. Webhook

- **Endpoint**: `POST https://giovannimavilla.app.n8n.cloud/webhook/size-recommend`
- **Content-Type**: `application/json`
- **Auth**: nessuna (il webhook è pubblico; se serve protezione la aggiungiamo)

### Request schema

```ts
interface SizeRecommendRequest {
  user_message: string;               // frase libera scritta dall'utente in chat
  target_product: {                   // contesto del prodotto che l'utente sta guardando
    brand: string;                    // es. 'OVS', 'Mango', 'Armani'
    name: string;                     // nome completo del prodotto
    product_url: string;              // URL canonico (anche placeholder, non viene chiamato)
    product_group: 'tops' | 'bottoms';
    product_type: string;             // es. 'shirt', 'shorts', 'skirt'
    sizes: Array<{
      size_label: string;             // es. 'M', 'L', '42', '28'
      // TOPS → chest, shoulder, sleeve, height, neck (cm, almeno una)
      // BOTTOMS → waist, hip, inseam, thigh (cm, almeno una)
      chest?:  number; shoulder?: number; sleeve?: number; height?: number; neck?: number;
      waist?:  number; hip?:      number; inseam?: number; thigh?:  number;
    }>;
  };
}
```

### Response schema

```ts
interface SizeRecommendResponse {
  message: string;                    // testo italiano 1-3 frasi da mostrare in chat
  user_ref: {
    brand: string | null;
    size_label: string | null;
    product_group: 'tops' | 'bottoms' | null;
    product_type: string | null;
    fit: 'slim' | 'regular' | 'oversize' | 'relaxed' | null;
    gender: 'men' | 'women' | 'unisex' | 'kids' | null;
    target_age: 'adult' | 'kids' | 'baby' | null;
  };
  result: {
    ok: boolean;
    error?: 'needs_clarification' | 'no_reference_found' | 'target_product_not_found'
          | 'no_comparable_measurements' | 'cannot_infer_product_group';
    confidence: 'high' | 'medium' | 'low' | 'none';
    recommended_size?: string;
    alternative_smaller?: { size_label: string; score: number };
    alternative_larger?:  { size_label: string; score: number };
    measurements_used?: string[];
    reference?: {                     // il capo di riferimento pescato dal DB
      brand: string; product_name: string; product_url: string;
      size_label: string; ml_product_type: string;
      measurements: Record<string, number | null>;
    };
    clarification?: {                 // presente solo se error='needs_clarification'
      kind: 'product_group' | 'product_type' | 'fit' | 'no_brand_data';
      candidates_groups?: string[];
      candidates_types?: string[];
      fits_seen?: string[];
    };
  };
}
```

### Comportamento del bot (UX)

- Se `result.ok == true` → mostra `message` come bolla del bot. Evidenzia `recommended_size`. Opzionalmente mostra alternative.
- Se `result.error == 'needs_clarification'` → `message` contiene una domanda; l'utente risponde con un'altra chiamata e il contesto (`target_product`) va **ri-passato identico**.
- Il bot è stateless: ogni richiesta porta con sé `user_message` + `target_product`. Non c'è conversation memory server-side.

### Flusso tipico

1. L'utente apre la pagina prodotto → il front-end ha già `target_product` in memoria.
2. L'utente scrive in chat `"Ho una Nike M oversize"` → POST al webhook con `user_message` + `target_product`.
3. Il bot risponde in italiano, 1–3 frasi, con la taglia consigliata.
4. Se il bot chiede chiarimenti, l'utente risponde `"oversize"` (o simile) → POST di nuovo, **stesso `target_product`**, il nuovo `user_message` contiene sia la risposta al chiarimento che il contesto originale (il front-end può concatenare i messaggi precedenti se serve, ma la cosa più semplice è che l'utente riscriva la frase più completa, es. `"Ho una Nike M oversize top"`).

---

## 2. Catalogo — 6 prodotti

### Product 1 — OVS — Blusa senza maniche in puro cotone blu regular fit LES COPAINS da Donna | OVS

| Campo | Valore |
|---|---|
| `id` | `p1` |
| `brand` | `OVS` |
| `name` | `Blusa senza maniche in puro cotone blu regular fit LES COPAINS da Donna | OVS` |
| `product_group` | `tops` |
| `product_type` | `shirt` |
| `leaf_category` | `Camicie regular` |
| `gender` | `women` |
| `category_path` | `Donna / Abbigliamento / Camicie e bluse` |
| `url` | `https://www.ovs.it/it/it/p/blusa-senza-maniche-in-puro-cotone-blu-regular-fit-002575265.html` |
| `image_placeholder` | `https://picsum.photos/seed/ovs-blusa-les-copains/640/800` |
| `price_mock` | `€49.9` |

**Descrizione**: Blusa senza maniche in puro cotone, fit regolare. Linea sobria e ariosa, ideale per la primavera-estate. Tessuto leggero, colletto tondo, finitura pulita sulle spalline.

**Tabella taglie (cm, midpoint se nel foglio c'era un range):**

| size_label | chest |
|---|---|
| 38 | 83 |
| 40 | 87 |
| 42 | 91 |
| 44 | 95 |
| 46 | 99 |
| 48 | 103 |
| 50 | 107 |
| 52 | 111 |
| XS | 84 |
| S | 89 |
| M | 95 |
| L | 101 |
| XL | 107 |
| XXL | 113 |
| XXXL | 120 |

**Payload `target_product` pronto all'uso:**

```json
{
  "brand": "OVS",
  "name": "Blusa senza maniche in puro cotone blu regular fit LES COPAINS da Donna | OVS",
  "product_url": "https://www.ovs.it/it/it/p/blusa-senza-maniche-in-puro-cotone-blu-regular-fit-002575265.html",
  "product_group": "tops",
  "product_type": "shirt",
  "sizes": [
    {
      "size_label": "38",
      "chest": 83.0
    },
    {
      "size_label": "40",
      "chest": 87.0
    },
    {
      "size_label": "42",
      "chest": 91.0
    },
    {
      "size_label": "44",
      "chest": 95.0
    },
    {
      "size_label": "46",
      "chest": 99.0
    },
    {
      "size_label": "48",
      "chest": 103.0
    },
    {
      "size_label": "50",
      "chest": 107.0
    },
    {
      "size_label": "52",
      "chest": 111.0
    },
    {
      "size_label": "XS",
      "chest": 84.0
    },
    {
      "size_label": "S",
      "chest": 89.0
    },
    {
      "size_label": "M",
      "chest": 95.0
    },
    {
      "size_label": "L",
      "chest": 101.0
    },
    {
      "size_label": "XL",
      "chest": 107.0
    },
    {
      "size_label": "XXL",
      "chest": 113.0
    },
    {
      "size_label": "XXXL",
      "chest": 120.0
    }
  ]
}
```

---

### Product 2 — Bonprix — Abito a fascia in maglia a costine

| Campo | Valore |
|---|---|
| `id` | `p2` |
| `brand` | `Bonprix` |
| `name` | `Abito a fascia in maglia a costine` |
| `product_group` | `tops` |
| `product_type` | `top` |
| `leaf_category` | `Donna` |
| `gender` | `women` |
| `category_path` | `Donna /  / ` |
| `url` | `https://www.bonprix.it/prodotto/abito-a-fascia-in-maglia-a-costine-nero-bianco-a-righe-933114/` |
| `image_placeholder` | `https://picsum.photos/seed/bonprix-abito-costine/640/800` |
| `price_mock` | `€29.99` |

**Descrizione**: Abito a fascia in maglia a costine, aderente, senza spalline. A righe nero/bianco. Perfetto da solo o sovrapposto.

**Tabella taglie (cm, midpoint se nel foglio c'era un range):**

| size_label | chest |
|---|---|
| 38 | 75.5 |
| 40 | 79.5 |
| 42 | 83.5 |
| 44 | 87.5 |
| 46 | 91.5 |
| 48 | 95.5 |
| 50 | 100 |
| 52 | 105 |
| 54 | 110.5 |
| 56 | 116.5 |
| 58 | 122.5 |
| 60 | 128.5 |
| 62 | 134.5 |
| 64 | 140.5 |

**Payload `target_product` pronto all'uso:**

```json
{
  "brand": "Bonprix",
  "name": "Abito a fascia in maglia a costine",
  "product_url": "https://www.bonprix.it/prodotto/abito-a-fascia-in-maglia-a-costine-nero-bianco-a-righe-933114/",
  "product_group": "tops",
  "product_type": "top",
  "sizes": [
    {
      "size_label": "38",
      "chest": 75.5
    },
    {
      "size_label": "40",
      "chest": 79.5
    },
    {
      "size_label": "42",
      "chest": 83.5
    },
    {
      "size_label": "44",
      "chest": 87.5
    },
    {
      "size_label": "46",
      "chest": 91.5
    },
    {
      "size_label": "48",
      "chest": 95.5
    },
    {
      "size_label": "50",
      "chest": 100.0
    },
    {
      "size_label": "52",
      "chest": 105.0
    },
    {
      "size_label": "54",
      "chest": 110.5
    },
    {
      "size_label": "56",
      "chest": 116.5
    },
    {
      "size_label": "58",
      "chest": 122.5
    },
    {
      "size_label": "60",
      "chest": 128.5
    },
    {
      "size_label": "62",
      "chest": 134.5
    },
    {
      "size_label": "64",
      "chest": 140.5
    }
  ]
}
```

---

### Product 3 — Mango — Blusa asimmetrica satinata

| Campo | Valore |
|---|---|
| `id` | `p3` |
| `brand` | `Mango` |
| `name` | `Blusa asimmetrica satinata` |
| `product_group` | `tops` |
| `product_type` | `shirt` |
| `leaf_category` | `Bluse` |
| `gender` | `women` |
| `category_path` | `Donna / Camicie e bluse / Bluse` |
| `url` | `https://shop.mango.com/it/it/p/donna/camicie-e-bluse/bluse/blusa-asimmetrica-satinata_27069059` |
| `image_placeholder` | `https://picsum.photos/seed/mango-blusa-satinata/640/800` |
| `price_mock` | `€39.99` |

**Descrizione**: Blusa asimmetrica in tessuto satinato. Design moderno con scollo asimmetrico e maniche lunghe morbide. Cade fluida sul corpo.

**Tabella taglie (cm, midpoint se nel foglio c'era un range):**

| size_label | chest |
|---|---|
| 1XL | 116 |
| 2XL | 124 |
| 3XL | 132 |
| 4XL | 140 |
| XXS | 78 |
| XS | 82 |
| S | 86 |
| M | 92 |
| L | 98 |
| XL | 104 |
| XXL | 110 |

**Payload `target_product` pronto all'uso:**

```json
{
  "brand": "Mango",
  "name": "Blusa asimmetrica satinata",
  "product_url": "https://shop.mango.com/it/it/p/donna/camicie-e-bluse/bluse/blusa-asimmetrica-satinata_27069059",
  "product_group": "tops",
  "product_type": "shirt",
  "sizes": [
    {
      "size_label": "1XL",
      "chest": 116.0
    },
    {
      "size_label": "2XL",
      "chest": 124.0
    },
    {
      "size_label": "3XL",
      "chest": 132.0
    },
    {
      "size_label": "4XL",
      "chest": 140.0
    },
    {
      "size_label": "XXS",
      "chest": 78.0
    },
    {
      "size_label": "XS",
      "chest": 82.0
    },
    {
      "size_label": "S",
      "chest": 86.0
    },
    {
      "size_label": "M",
      "chest": 92.0
    },
    {
      "size_label": "L",
      "chest": 98.0
    },
    {
      "size_label": "XL",
      "chest": 104.0
    },
    {
      "size_label": "XXL",
      "chest": 110.0
    }
  ]
}
```

---

### Product 4 — Armani — Bermuda con coulisse in twill di cotone | Armani Exchange

| Campo | Valore |
|---|---|
| `id` | `p4` |
| `brand` | `Armani` |
| `name` | `Bermuda con coulisse in twill di cotone | Armani Exchange` |
| `product_group` | `bottoms` |
| `product_type` | `shorts` |
| `leaf_category` | `Armani exchange` |
| `gender` | `men` |
| `category_path` | `Armani exchange /  / ` |
| `url` | `https://www.armani.com/it-it/armani-exchange/bermuda-con-coulisse-in-twill-di-cotone-cod-XM002741-AF23202-U6229/` |
| `image_placeholder` | `https://picsum.photos/seed/armani-bermuda-twill/640/800` |
| `price_mock` | `€69.0` |

**Descrizione**: Bermuda in twill di cotone con coulisse in vita. Taglio rilassato, finiture pulite, tasche laterali. Perfetto per il casual smart estivo.

**Tabella taglie (cm, midpoint se nel foglio c'era un range):**

| size_label | waist | hip |
|---|---|---|
| 26 | 66.5 | 87 |
| 26_R | 66.5 | 87 |
| 26_S | 66.5 | 87 |
| 27 | 70 | 89 |
| 27_R | 70 | 89 |
| 27_S | 70 | 89 |
| 28 | 72 | 91 |
| 28_R | 72 | 91 |
| 28_S | 72 | 91 |
| 29 | 74 | 93 |
| 29_R | 74 | 93 |
| 29_S | 74 | 93 |
| 30 | 77 | 95.5 |
| 30_R | 77 | 95.5 |
| 30_S | 77 | 95.5 |
| 31 | 79 | 98 |
| 31_R | 79 | 98 |
| 31_S | 79 | 98 |
| 32 | 82 | 100 |
| 32_R | 82 | 100 |
| 32_S | 82 | 100 |
| 33 | 84 | 102 |
| 33_R | 84 | 102 |
| 33_S | 84 | 102 |
| 34 | 87 | 104 |
| 34_R | 87 | 104 |
| 34_S | 87 | 104 |
| 35 | 89 | 106 |
| 35_R | 89 | 106 |
| 35_S | 89 | 106 |
| 36 | 92 | 108 |
| 36_R | 92 | 108 |
| 36_S | 92 | 108 |
| 38 | 97.5 | 112.5 |
| 38_R | 97.5 | 112.5 |
| 38_S | 97.5 | 112.5 |
| 40 | 102.5 | 117 |
| 40_R | 102.5 | 117 |
| 40_S | 102.5 | 117 |
| 42 | 107.5 | 121.5 |
| 42_R | 107.5 | 121.5 |
| 42_S | 107.5 | 121.5 |
| 44 | 112.5 | 126.5 |
| 44_R | 112.5 | 126.5 |
| 44_S | 112.5 | 126.5 |

**Payload `target_product` pronto all'uso:**

```json
{
  "brand": "Armani",
  "name": "Bermuda con coulisse in twill di cotone | Armani Exchange",
  "product_url": "https://www.armani.com/it-it/armani-exchange/bermuda-con-coulisse-in-twill-di-cotone-cod-XM002741-AF23202-U6229/",
  "product_group": "bottoms",
  "product_type": "shorts",
  "sizes": [
    {
      "size_label": "26",
      "waist": 66.5,
      "hip": 87.0
    },
    {
      "size_label": "26_R",
      "waist": 66.5,
      "hip": 87.0
    },
    {
      "size_label": "26_S",
      "waist": 66.5,
      "hip": 87.0
    },
    {
      "size_label": "27",
      "waist": 70.0,
      "hip": 89.0
    },
    {
      "size_label": "27_R",
      "waist": 70.0,
      "hip": 89.0
    },
    {
      "size_label": "27_S",
      "waist": 70.0,
      "hip": 89.0
    },
    {
      "size_label": "28",
      "waist": 72.0,
      "hip": 91.0
    },
    {
      "size_label": "28_R",
      "waist": 72.0,
      "hip": 91.0
    },
    {
      "size_label": "28_S",
      "waist": 72.0,
      "hip": 91.0
    },
    {
      "size_label": "29",
      "waist": 74.0,
      "hip": 93.0
    },
    {
      "size_label": "29_R",
      "waist": 74.0,
      "hip": 93.0
    },
    {
      "size_label": "29_S",
      "waist": 74.0,
      "hip": 93.0
    },
    {
      "size_label": "30",
      "waist": 77.0,
      "hip": 95.5
    },
    {
      "size_label": "30_R",
      "waist": 77.0,
      "hip": 95.5
    },
    {
      "size_label": "30_S",
      "waist": 77.0,
      "hip": 95.5
    },
    {
      "size_label": "31",
      "waist": 79.0,
      "hip": 98.0
    },
    {
      "size_label": "31_R",
      "waist": 79.0,
      "hip": 98.0
    },
    {
      "size_label": "31_S",
      "waist": 79.0,
      "hip": 98.0
    },
    {
      "size_label": "32",
      "waist": 82.0,
      "hip": 100.0
    },
    {
      "size_label": "32_R",
      "waist": 82.0,
      "hip": 100.0
    },
    {
      "size_label": "32_S",
      "waist": 82.0,
      "hip": 100.0
    },
    {
      "size_label": "33",
      "waist": 84.0,
      "hip": 102.0
    },
    {
      "size_label": "33_R",
      "waist": 84.0,
      "hip": 102.0
    },
    {
      "size_label": "33_S",
      "waist": 84.0,
      "hip": 102.0
    },
    {
      "size_label": "34",
      "waist": 87.0,
      "hip": 104.0
    },
    {
      "size_label": "34_R",
      "waist": 87.0,
      "hip": 104.0
    },
    {
      "size_label": "34_S",
      "waist": 87.0,
      "hip": 104.0
    },
    {
      "size_label": "35",
      "waist": 89.0,
      "hip": 106.0
    },
    {
      "size_label": "35_R",
      "waist": 89.0,
      "hip": 106.0
    },
    {
      "size_label": "35_S",
      "waist": 89.0,
      "hip": 106.0
    },
    {
      "size_label": "36",
      "waist": 92.0,
      "hip": 108.0
    },
    {
      "size_label": "36_R",
      "waist": 92.0,
      "hip": 108.0
    },
    {
      "size_label": "36_S",
      "waist": 92.0,
      "hip": 108.0
    },
    {
      "size_label": "38",
      "waist": 97.5,
      "hip": 112.5
    },
    {
      "size_label": "38_R",
      "waist": 97.5,
      "hip": 112.5
    },
    {
      "size_label": "38_S",
      "waist": 97.5,
      "hip": 112.5
    },
    {
      "size_label": "40",
      "waist": 102.5,
      "hip": 117.0
    },
    {
      "size_label": "40_R",
      "waist": 102.5,
      "hip": 117.0
    },
    {
      "size_label": "40_S",
      "waist": 102.5,
      "hip": 117.0
    },
    {
      "size_label": "42",
      "waist": 107.5,
      "hip": 121.5
    },
    {
      "size_label": "42_R",
      "waist": 107.5,
      "hip": 121.5
    },
    {
      "size_label": "42_S",
      "waist": 107.5,
      "hip": 121.5
    },
    {
      "size_label": "44",
      "waist": 112.5,
      "hip": 126.5
    },
    {
      "size_label": "44_R",
      "waist": 112.5,
      "hip": 126.5
    },
    {
      "size_label": "44_S",
      "waist": 112.5,
      "hip": 126.5
    }
  ]
}
```

---

### Product 5 — Mango — Gonna crochet ricamata con fiori

| Campo | Valore |
|---|---|
| `id` | `p5` |
| `brand` | `Mango` |
| `name` | `Gonna crochet ricamata con fiori` |
| `product_group` | `bottoms` |
| `product_type` | `skirt` |
| `leaf_category` | `Corte` |
| `gender` | `women` |
| `category_path` | `Donna / Gonne / Corte` |
| `url` | `https://shop.mango.com/it/it/p/donna/gonne/corte/gonna-crochet-ricamata-con-fiori_27099057` |
| `image_placeholder` | `https://picsum.photos/seed/mango-gonna-crochet/640/800` |
| `price_mock` | `€59.99` |

**Descrizione**: Gonna corta in crochet con ricami floreali. Fodera interna, vita elasticizzata. Stile boho-chic, ottima per la stagione calda.

**Tabella taglie (cm, midpoint se nel foglio c'era un range):**

| size_label | waist | hip |
|---|---|---|
| 1XL | 99 | 124 |
| 1XL-2XL | 106 | 130 |
| 2XL | 106 | 130 |
| 3XL | 113 | 136 |
| 3XL-4XL | 120 | 142 |
| 4XL | 120 | 142 |
| 36 | 59 | 86 |
| 38 | 62 | 90 |
| 40 | 66 | 94 |
| 42 | 70 | 98 |
| 44 | 74 | 102 |
| 46 | 78 | 106 |
| 48 | 85 | 112 |
| 50 | 92 | 118 |
| 52 | 97 | 122 |
| 54 | 102 | 126 |
| 56 | 107 | 130 |
| 58 | 112 | 134 |
| XXS | 59 | 86 |
| XS | 62 | 90 |
| S | 66 | 94 |
| M | 72 | 100 |
| L | 78 | 106 |
| XL | 85 | 112 |
| XXL | 92 | 118 |
| L-XL | 85 | 112 |
| S-M | 72 | 100 |
| XXS-XS | 62 | 90 |

**Payload `target_product` pronto all'uso:**

```json
{
  "brand": "Mango",
  "name": "Gonna crochet ricamata con fiori",
  "product_url": "https://shop.mango.com/it/it/p/donna/gonne/corte/gonna-crochet-ricamata-con-fiori_27099057",
  "product_group": "bottoms",
  "product_type": "skirt",
  "sizes": [
    {
      "size_label": "1XL",
      "waist": 99.0,
      "hip": 124.0
    },
    {
      "size_label": "1XL-2XL",
      "waist": 106.0,
      "hip": 130.0
    },
    {
      "size_label": "2XL",
      "waist": 106.0,
      "hip": 130.0
    },
    {
      "size_label": "3XL",
      "waist": 113.0,
      "hip": 136.0
    },
    {
      "size_label": "3XL-4XL",
      "waist": 120.0,
      "hip": 142.0
    },
    {
      "size_label": "4XL",
      "waist": 120.0,
      "hip": 142.0
    },
    {
      "size_label": "36",
      "waist": 59.0,
      "hip": 86.0
    },
    {
      "size_label": "38",
      "waist": 62.0,
      "hip": 90.0
    },
    {
      "size_label": "40",
      "waist": 66.0,
      "hip": 94.0
    },
    {
      "size_label": "42",
      "waist": 70.0,
      "hip": 98.0
    },
    {
      "size_label": "44",
      "waist": 74.0,
      "hip": 102.0
    },
    {
      "size_label": "46",
      "waist": 78.0,
      "hip": 106.0
    },
    {
      "size_label": "48",
      "waist": 85.0,
      "hip": 112.0
    },
    {
      "size_label": "50",
      "waist": 92.0,
      "hip": 118.0
    },
    {
      "size_label": "52",
      "waist": 97.0,
      "hip": 122.0
    },
    {
      "size_label": "54",
      "waist": 102.0,
      "hip": 126.0
    },
    {
      "size_label": "56",
      "waist": 107.0,
      "hip": 130.0
    },
    {
      "size_label": "58",
      "waist": 112.0,
      "hip": 134.0
    },
    {
      "size_label": "XXS",
      "waist": 59.0,
      "hip": 86.0
    },
    {
      "size_label": "XS",
      "waist": 62.0,
      "hip": 90.0
    },
    {
      "size_label": "S",
      "waist": 66.0,
      "hip": 94.0
    },
    {
      "size_label": "M",
      "waist": 72.0,
      "hip": 100.0
    },
    {
      "size_label": "L",
      "waist": 78.0,
      "hip": 106.0
    },
    {
      "size_label": "XL",
      "waist": 85.0,
      "hip": 112.0
    },
    {
      "size_label": "XXL",
      "waist": 92.0,
      "hip": 118.0
    },
    {
      "size_label": "L-XL",
      "waist": 85.0,
      "hip": 112.0
    },
    {
      "size_label": "S-M",
      "waist": 72.0,
      "hip": 100.0
    },
    {
      "size_label": "XXS-XS",
      "waist": 62.0,
      "hip": 90.0
    }
  ]
}
```

---

### Product 6 — OVS — Gonna beige lunga in puro cotone LES COPAINS da Donna | OVS

| Campo | Valore |
|---|---|
| `id` | `p6` |
| `brand` | `OVS` |
| `name` | `Gonna beige lunga in puro cotone LES COPAINS da Donna | OVS` |
| `product_group` | `bottoms` |
| `product_type` | `skirt` |
| `leaf_category` | `Gonne lunghe` |
| `gender` | `women` |
| `category_path` | `Donna / Abbigliamento / Gonne` |
| `url` | `https://www.ovs.it/it/it/p/gonna-beige-lunga-in-puro-cotone-002559139.html` |
| `image_placeholder` | `https://picsum.photos/seed/ovs-gonna-les-copains/640/800` |
| `price_mock` | `€79.9` |

**Descrizione**: Gonna lunga in puro cotone, tono beige caldo. Taglio svasato fino alla caviglia, vita alta, tessuto strutturato.

**Tabella taglie (cm, midpoint se nel foglio c'era un range):**

| size_label | waist | hip |
|---|---|---|
| 38 | 63 | 89 |
| 40 | 67 | 93 |
| 42 | 71 | 97 |
| 44 | 75 | 101 |
| 46 | 79 | 105 |
| 48 | 83 | 109 |
| 50 | 87 | 113 |
| 52 | 91 | 117 |
| XS | 64 | 90 |
| S | 69 | 95 |
| M | 75 | 101 |
| L | 81 | 107 |
| XL | 87 | 113 |
| XXL | 93 | 119 |
| XXXL | 100 | 126 |

**Payload `target_product` pronto all'uso:**

```json
{
  "brand": "OVS",
  "name": "Gonna beige lunga in puro cotone LES COPAINS da Donna | OVS",
  "product_url": "https://www.ovs.it/it/it/p/gonna-beige-lunga-in-puro-cotone-002559139.html",
  "product_group": "bottoms",
  "product_type": "skirt",
  "sizes": [
    {
      "size_label": "38",
      "waist": 63.0,
      "hip": 89.0
    },
    {
      "size_label": "40",
      "waist": 67.0,
      "hip": 93.0
    },
    {
      "size_label": "42",
      "waist": 71.0,
      "hip": 97.0
    },
    {
      "size_label": "44",
      "waist": 75.0,
      "hip": 101.0
    },
    {
      "size_label": "46",
      "waist": 79.0,
      "hip": 105.0
    },
    {
      "size_label": "48",
      "waist": 83.0,
      "hip": 109.0
    },
    {
      "size_label": "50",
      "waist": 87.0,
      "hip": 113.0
    },
    {
      "size_label": "52",
      "waist": 91.0,
      "hip": 117.0
    },
    {
      "size_label": "XS",
      "waist": 64.0,
      "hip": 90.0
    },
    {
      "size_label": "S",
      "waist": 69.0,
      "hip": 95.0
    },
    {
      "size_label": "M",
      "waist": 75.0,
      "hip": 101.0
    },
    {
      "size_label": "L",
      "waist": 81.0,
      "hip": 107.0
    },
    {
      "size_label": "XL",
      "waist": 87.0,
      "hip": 113.0
    },
    {
      "size_label": "XXL",
      "waist": 93.0,
      "hip": 119.0
    },
    {
      "size_label": "XXXL",
      "waist": 100.0,
      "hip": 126.0
    }
  ]
}
```

---

## 3. Prompt utente di esempio (per test)

Per ciascun prodotto puoi testare queste frasi utente. Il bot dovrebbe rispondere con una taglia consigliata oppure fare UNA domanda chiarificatrice se l'input è troppo vago.

### Prompt ricchi (dovrebbero raccomandare subito)

- "Ho una Nike M oversize che mi sta bene"
- "Ho una Mango 42 pantaloni"
- "Ho una OVS L felpa che mi veste regolare"
- "Ho una Armani 44 camicia da uomo"
- "Ho una Bonprix 48 da donna"

### Prompt poveri (dovrebbero attivare la clarification)

- "Ho una L di OVS"
- "Ho una 42 di Mango"
- "Ho una M di Armani"
- "Ho una XL"

### Prompt edge-case (dovrebbero essere gestiti con garbo)

- "Ho una Gucci L"
- "Non so che taglia ho"
- "Ho una Nike M tshirt"


---

## 4. Note pratiche per il front-end

- **Latenza tipica**: 4–12 secondi (due chiamate LLM + lettura foglio di ~9500 righe per trovare il reference). Mostra un loader.
- **Transient errors**: se `fetch` ritorna 502/503/504, riprova una volta dopo 2s. Dopo il secondo fallimento, mostra un messaggio neutro.
- **Stateless**: ogni richiesta è indipendente. Se vuoi mostrare la conversazione in chat, tieni la history lato client.
- **Ri-passare sempre `target_product`**: il back-end non sa su quale prodotto sei; il front-end deve includerlo ad ogni POST.
- **Messaggi markdown-light**: il campo `message` può contenere `**grassetto**`; parsalo prima di renderizzare.
