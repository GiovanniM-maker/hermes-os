# Size Comparator — Regole per il frontend (da passare a GPT)

## Principio chiave — il bot è stateless

Il webhook **non ha memoria** tra chiamate. Non tenere stato server-side. Ogni
POST deve portare con sé tutto il contesto necessario per quel turno:
`user_message` (cosa l'utente sta dicendo ORA) + `target_product` (il prodotto
che l'utente sta guardando sulla pagina).

La responsabilità di "ricordare la conversazione" è **esclusivamente del
frontend**. Il backend non va modificato per gestire history.

---

## Endpoint

```
POST https://giovannimavilla.app.n8n.cloud/webhook/size-recommend
Content-Type: application/json
```

---

## Regole di invio — una per una

### Regola 1: un turno utente = una POST

Quando l'utente preme Invio sulla chat, il frontend fa **una** POST. Non
ritardare, non raggruppare turni.

### Regola 2: `user_message` è SOLO l'ultimo messaggio dell'utente

NON concatenare la history. Non inviare mai:

```js
// ❌ NO — fa impazzire l'extractor, può estrarre un capo sbagliato
user_message: history.map(m => m.text).join('\n')
```

Invia solo:

```js
// ✅ SÌ
user_message: latestUserText
```

### Regola 3: `target_product` è IDENTICO a ogni turno della stessa pagina

Tienilo in uno state della pagina prodotto (Redux/Zustand/Context/localStorage,
come preferisce GPT). A ogni POST ripassalo **così com'è**. Il backend deve
ricevere sempre la stessa forma, altrimenti perde riferimento al prodotto.

### Regola 4: Gestire la clarification fondendo i messaggi

Se il bot risponde con `result.error === 'needs_clarification'`, il suo
`message` è una domanda. Quando l'utente risponde, il frontend deve **fondere**
la risposta con il precedente user_message prima di inviarla, altrimenti il
backend (che è stateless) non può correlare la risposta alla domanda.

Strategia consigliata per MVP: tieni in state l'ultimo `user_message` inviato.
Quando ricevi una risposta di clarification, concatena "Messaggio precedente +
risposta utente" in una singola frase naturale per il prossimo turno.

```js
// Stato pagina
let lastUserMessage = '';
let lastBotNeedsClarification = false;

async function sendTurn(userText) {
  let payloadUserMessage = userText;

  if (lastBotNeedsClarification && lastUserMessage) {
    // Fondi: "ho una camicia dell'OVS" + "L" → "ho una camicia dell'OVS L"
    payloadUserMessage = `${lastUserMessage} ${userText}`.trim();
  }

  const res = await fetchWithRetry('/webhook/size-recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_message: payloadUserMessage,
      target_product: currentProductContext,  // sempre lo stesso per la pagina
    }),
  });

  const data = await res.json();

  // Update UI
  appendBotBubble(data.message);
  if (data.result?.ok && data.result.comparison) {
    renderComparisonTable(data.result);
  }

  // Update state per il prossimo turno
  lastBotNeedsClarification = (data.result?.error === 'needs_clarification');
  lastUserMessage = payloadUserMessage;
}
```

### Regola 5: Retry su errori transient

L'istanza n8n Cloud può dare 502/503/504 o timeout quando è in sleep.
Retry semplice:

```js
async function fetchWithRetry(url, opts, attempts = 3) {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url, opts);
      if (res.ok) return res;
      if (res.status >= 500 && res.status < 600 && i < attempts - 1) {
        await sleep(2000 * (i + 1));  // 2s, 4s, 6s
        continue;
      }
      throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      if (i === attempts - 1) throw e;
      await sleep(2000 * (i + 1));
    }
  }
}
```

Durante i retry mostra in UI un loader tipo "Sto svegliando il bot…".

### Regola 6: Gestisci tutti i casi di `result.error`

Il bot può rispondere con `ok=true` oppure con vari errori. In ogni caso
`message` contiene testo umano pronto per la UI — mostralo sempre. Poi:

| `result.error` | Cosa fare oltre a mostrare `message` |
|---|---|
| _(nessun error, `ok:true`)_ | Renderizza `result.comparison` come tabella + evidenzia `recommended_size` |
| `needs_clarification` | Mostra solo `message`. Setta `lastBotNeedsClarification = true` così il prossimo turno verrà fuso (Regola 4) |
| `no_reference_found` | Mostra `message`. Niente tabella |
| `target_product_not_found` | Mostra `message`. Niente tabella. Verifica lato FE che `target_product` sia stato inviato |
| `no_comparable_measurements` | Mostra `message`. Niente tabella |
| `cannot_infer_product_group` | Mostra `message`. Come clarification, setta `lastBotNeedsClarification = true` |

### Regola 7: Quando l'utente cambia pagina prodotto, resetta lo stato conversazionale

```js
useEffect(() => {
  setLastUserMessage('');
  setLastBotNeedsClarification(false);
  setChatHistory([]);
}, [productId]);  // reset ogni volta che l'utente apre un prodotto diverso
```

Perché: se l'utente stava parlando di Armani 44 sulla pagina X e passa alla
pagina Y, la conversazione deve ripartire pulita.

---

## Rendering della risposta

### 1. Bolla chat

Mostra `response.message` come bolla del bot. Supporta `**bold**` markdown-light
(semplice sostituzione regex va bene per l'MVP).

### 2. Tabella comparativa — solo se `result.ok === true`

`result.comparison` contiene già tutto quello che serve:

```ts
interface Comparison {
  group: 'tops' | 'bottoms';
  measurements_used: string[];   // misure usate per il match, es. ['chest']
  measurements_labels: string[]; // tutte le misure rilevanti per il gruppo
  reference: {
    brand: string;
    size_label: string;
    product_name: string;
    ml_product_type: string;
    measurements: Record<string, number | null>;
  };
  target: {
    brand: string | null;
    product_type: string | null;
    product_name: string | null;
  };
  rows: Array<{
    size_label: string;
    role: 'alternative_smaller' | 'recommended' | 'alternative_larger';
    measurements: Record<string, number | null>;
    diffs: Record<string, { cm: number; pct: number } | null>;
  }>;
}
```

Rendering suggerito:

```
Riferimento: {reference.brand} {reference.size_label}
  → {reference.measurements[k]} cm per ogni k in measurements_used

┌────────────────┬──────────────┬──────────────────────────────┐
│ Taglia         │ {k1} / {k2}  │ vs. tua {reference.brand}   │
├────────────────┼──────────────┼──────────────────────────────┤
│ S  (smaller)   │ 89           │ −4,5 cm  (−4,8%)             │
│ M  (raccomand) │ 95  ⭐       │ +1,5 cm  (+1,6%)             │
│ L  (larger)    │ 101          │ +7,5 cm  (+8,0%)             │
└────────────────┴──────────────┴──────────────────────────────┘
Misure usate per il match: chest
```

Note:
- Le `rows` arrivano già ordinate `smaller → recommended → larger`: mantieni
  quell'ordine.
- Mostra solo le colonne in `measurements_used` (le altre sono `null`).
- `diffs[k].pct` è decimale (0.016 = 1.6%): moltiplica × 100.
- Formatta `cm` con segno esplicito: `+1,5` / `−4,5` (il segno è già nel valore).
- Evidenzia la riga con `role === 'recommended'`.

---

## Cosa NON fare

- ❌ Non concatenare la history e mandarla come `user_message`.
- ❌ Non dimenticare `target_product` in qualche turno (senza quello il bot
  non sa cosa stai guardando).
- ❌ Non re-inviare la stessa richiesta più volte in parallelo.
- ❌ Non rispondere all'utente con testo inventato sul frontend: il bot
  risponde sempre con `message`, usa quello.
- ❌ Non aggiungere brand o prodotti non presenti in `target_product` nella
  UI — il bot non lo fa e la UI non deve.

---

## Esempio completo — flusso con clarification

1. Utente su pagina "OVS Blusa LES COPAINS". Frontend ha `target_product`
   in state.
2. Utente scrive: `"ho una camicia dell'OVS"`.
3. Frontend POST: `{ user_message: "ho una camicia dell'OVS", target_product: {…} }`.
4. Bot risponde con `result.error = 'needs_clarification'`,
   `message = "Che taglia è la tua camicia OVS?"`.
5. Frontend mostra la bolla, setta `lastBotNeedsClarification = true`,
   `lastUserMessage = "ho una camicia dell'OVS"`.
6. Utente scrive: `"L"`.
7. Frontend fonde: `payloadUserMessage = "ho una camicia dell'OVS L"`.
8. POST: `{ user_message: "ho una camicia dell'OVS L", target_product: {…} }`.
9. Bot risponde con `result.ok = true`, `recommended_size = "L"`, comparison
   completa.
10. Frontend mostra la bolla + la tabella. Resetta `lastBotNeedsClarification`.

Fine.
