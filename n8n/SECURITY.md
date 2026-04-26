# Secret handling

## Regola unica

**Nessun secret nel repository.** Mai.

Secret = API keys, bot tokens, service-account JSON, OAuth client secrets,
private keys, basic-auth credentials in URL, password.

## Dove vanno i secret

- **n8n credentials store** (cifrato lato n8n). Vedi n8n → Credentials.
  I workflow JSON referenziano la credential **per ID**, mai per valore.
- In alternativa, variabili d'ambiente sul container n8n (solo per
  deployment self-hosted; su n8n Cloud sono Enterprise-only).

## Controllo rapido prima di committare

Prima di `git add`/`git commit` su file dentro `n8n/workflows/`,
esegui:

```bash
grep -nE "AIza[A-Za-z0-9_-]{35}|sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9._-]{50,}|[0-9]{8,}:[A-Za-z0-9_-]{30,}" n8n/
```

Se ritorna righe, **non committare**. Sposta il valore in una credential
n8n e rimpiazza il valore nel JSON con una referenza credential.

## Pattern di referenza credential in un HTTP Request

```json
{
  "authentication": "predefinedCredentialType",
  "nodeCredentialType": "googlePalmApi",
  "credentials": {
    "googlePalmApi": { "id": "<CRED_ID>", "name": "<display>" }
  }
}
```

`<CRED_ID>` è sempre sicuro da committare — è un identificatore opaco
gestito da n8n, non il secret.

## Se un secret è già stato committato

1. **Revoca la credential** sul provider (AI Studio, BotFather, ecc.).
2. **Rigeneralo** e mettilo nella credential n8n corretta.
3. **Riscrivi la history git** rimuovendo il valore dai commit passati:
   ```bash
   git filter-branch --force --tree-filter "
     sed -i 's/<OLD_SECRET>/<PLACEHOLDER>/g' path/to/file
   " -- --all
   git for-each-ref --format='%(refname)' refs/original/ | xargs -n 1 git update-ref -d
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   git push --force --all
   ```
4. **Nota**: il force-push non cancella i commit dalla cache di GitHub
   e da eventuali fork. Il secret va considerato bruciato a vita.
