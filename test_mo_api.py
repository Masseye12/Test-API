"""
Banc de test - API middle-office SenyoneBank
LECTURE SEULE. Aucun appel de ce script ne modifie quoi que ce soit.

Usage :
    python test_mo_api.py
    python test_mo_api.py --extraction EXT-20260903-123400

Le secret est lu dans l'environnement ou dans un fichier .env voisin.
Il n'est jamais affiche ni journalise.
"""

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DEFAUT = "https://demo.senyone.sn/bank/api"
TIMEOUT = 20

# Routes que ce script n'appellera JAMAIS : elles ecrivent dans une chaine comptable.
INTERDITES = {
    "POST /api/sync/entry-result",
    "POST /api/sync/statement",
    "POST /api/sync/steps",
    "POST /api/sync/anomaly-report",
    "POST /api/sync/provisioning-result",
    "POST /api/demo/scenarios/{key}",
}

VERT, ROUGE, JAUNE, GRIS, RAZ = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"


def charger_env():
    """Charge un .env voisin sans ecraser l'environnement existant."""
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(chemin):
        return
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, _, val = ligne.partition("=")
            os.environ.setdefault(cle.strip(), val.strip().strip('"').strip("'"))


def masquer(secret):
    if not secret:
        return "(absent)"
    return f"{secret[:3]}...{secret[-2:]} ({len(secret)} car.)"


def appeler(methode, url, token=None, attendu=None):
    """Retourne (code, corps_texte, duree_ms, erreur_reseau)."""
    req = urllib.request.Request(url, method=methode)
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    ctx = ssl.create_default_context()
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            corps = r.read().decode("utf-8", "replace")
            return r.status, corps, int((time.time() - t0) * 1000), None
    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", "replace")
        return e.code, corps, int((time.time() - t0) * 1000), None
    except Exception as e:                                  # reseau, DNS, TLS
        return None, "", int((time.time() - t0) * 1000), f"{type(e).__name__}: {e}"


def verdict(code, attendus):
    if code is None:
        return f"{ROUGE}INJOIGNABLE{RAZ}"
    if code in attendus:
        return f"{VERT}OK{RAZ}"
    return f"{ROUGE}INATTENDU{RAZ}"


def apercu(corps, n=220):
    corps = " ".join(corps.split())
    return corps[:n] + ("..." if len(corps) > n else "")


def titre(t):
    print(f"\n{'-' * 72}\n{t}\n{'-' * 72}")


def main():
    charger_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("MO_BASE_URL", BASE_DEFAUT))
    ap.add_argument("--extraction", default=os.environ.get("MO_EXTRACTION_ID"),
                    help="Un EXT-20260922-121725 existant, pour tester progress")
    args = ap.parse_args()

    token = os.environ.get("SYNC_MACHINE_SECRET")
    base = args.base.rstrip("/")

    print(f"\nBanc de test middle-office  -  LECTURE SEULE")
    print(f"Base      : {base}")
    print(f"Secret    : {masquer(token)}")
    print(f"Extraction: {args.extraction or '(non fournie)'}")
    print(f"{GRIS}Routes ecrivantes volontairement exclues : "
          f"{len(INTERDITES)}{RAZ}")

    resultats = []

    # ----------------------------------------------------------------
    #                           1. socle
    # ----------------------------------------------------------------
    titre("1. Le service repond-il ?")
    url = f"{base}/openapi.json"
    code, corps, ms, err = appeler("GET", url)
    print(f"GET /openapi.json        {code}  {ms} ms  {verdict(code, {200})}")
    if err:
        print(f"  {ROUGE}{err}{RAZ}")
        print(f"\n{ROUGE}Le service est injoignable. Les tests suivants n'ont pas de sens.{RAZ}")
        print(f"{GRIS}Verifie le reseau, le proxy d'entreprise, et que l'URL de base est la bonne.{RAZ}\n")
        return 2
    resultats.append(("GET /openapi.json", code, ms))

    paths = []
    if code == 200:
        try:
            spec = json.loads(corps)
            paths = sorted(spec.get("paths", {}).keys())
            print(f"  {len(paths)} routes exposees")
            for p in paths:
                methodes = ",".join(m.upper() for m in spec["paths"][p]
                                    if m in ("get", "post", "put", "patch", "delete"))
                marque = f"  {JAUNE}<- ecrit{RAZ}" if any(
                    f"{m} {p}" in INTERDITES for m in methodes.split(",")) else ""
                print(f"    {methodes:12} {p}{marque}")
            manquantes = [r for r in ("/api/sync/progress", "/api/sync/statement",
                                      "/api/sync/entry-result", "/api/sync/steps")
                          if r not in paths]
            if manquantes:
                print(f"  {JAUNE}Absentes de la spec : {', '.join(manquantes)}{RAZ}")
            # Le pattern d'extractionId, si la spec le porte
            txt = json.dumps(spec)
            if "EXT-" in txt:
                import re
                for m in set(re.findall(r'"pattern"\s*:\s*"([^"]*EXT[^"]*)"', txt)):
                    print(f"  pattern extractionId : {m}")
        except json.JSONDecodeError:
            print(f"  {JAUNE}Reponse non-JSON{RAZ}")

    # --------------------------------------------------
    #                    2. authentification
    # --------------------------------------------------

    titre("2. L'authentification se comporte-t-elle correctement ?")
    cible = f"{base}/sync/progress"

    code, corps, ms, _ = appeler("GET", cible)
    print(f"sans jeton               {code}  {ms} ms  {verdict(code, {401, 400})}")
    print(f"  corps : {apercu(corps) or GRIS + '(vide - 401 muet)' + RAZ}")

    code, corps, ms, _ = appeler("GET", cible, token="jeton-volontairement-faux")
    print(f"jeton invalide           {code}  {ms} ms  {verdict(code, {401})}")
    print(f"  corps : {apercu(corps) or GRIS + '(vide - 401 muet)' + RAZ}")

    if not token:
        print(f"\n{JAUNE}SYNC_MACHINE_SECRET absent : les tests authentifies sont sautes.{RAZ}")
        print(f"{GRIS}Renseigne-le dans ApiTests/.env (voir .env.example).{RAZ}\n")
        return 1

    # ------------------------------------------- 
    #       3. progress, la question ouverte
    # -------------------------------------------
    titre("3. GET /sync/progress  -  quel parametre attend-il ?")
    essais = [
        ("sans parametre", cible),
        ("?id=",           f"{cible}?id={urllib.parse.quote(args.extraction)}" if args.extraction else None),
        ("?extractionId=", f"{cible}?extractionId={urllib.parse.quote(args.extraction)}" if args.extraction else None),
    ]
    gagnant = None
    for libelle, u in essais:
        if u is None:
            print(f"{libelle:16}         {GRIS}saute - passe --extraction EXT-...{RAZ}")
            continue
        code, corps, ms, _ = appeler("GET", u, token=token)
        print(f"{libelle:16}         {code}  {ms} ms  {verdict(code, {200})}")
        print(f"  {apercu(corps)}")
        if code == 200 and gagnant is None:
            gagnant = (libelle, corps)
        resultats.append((f"GET /sync/progress {libelle}", code, ms))

    if gagnant:
        libelle, corps = gagnant
        print(f"\n{VERT}Parametre retenu : {libelle}{RAZ}")
        try:
            d = json.loads(corps)
            comptes = d.get("accounts", [])
            print(f"  extractionId : {d.get('extractionId')}")
            print(f"  scope        : {d.get('scope')}")
            print(f"  finished     : {d.get('finished')}   complete : {d.get('complete')}")
            print(f"  lines        : {d.get('lines')}")
            print(f"  comptes      : {len(comptes)}")
            if comptes:
                print(f"  champs d'un compte : {sorted(comptes[0].keys())}")
                bloques = sum(1 for c in comptes if c.get("blocked"))
                rendus = sum(1 for c in comptes if c.get("statementReceived"))
                print(f"  bloques {bloques} / releves recus {rendus} / total {len(comptes)}")
        except (json.JSONDecodeError, AttributeError):
            print(f"  {JAUNE}Corps non exploitable{RAZ}")

    # -------------------------------------------------------
    #                    4. extraction
    # -------------------------------------------------------

    titre("4. GET /sync/extraction")
    for libelle, u in [("sans parametre", f"{base}/sync/extraction"),
                       ("?id=", f"{base}/sync/extraction?id={urllib.parse.quote(args.extraction)}"
                        if args.extraction else None)]:
        if u is None:
            continue
        code, corps, ms, _ = appeler("GET", u, token=token)
        print(f"{libelle:16}         {code}  {ms} ms  {verdict(code, {200})}")
        print(f"  {apercu(corps)}")
        resultats.append((f"GET /sync/extraction {libelle}", code, ms))

    # ------------------------------------------------------------- 
    #                           synthese
    # -------------------------------------------------------------

    titre("Synthese")
    for nom, code, ms in resultats:
        etat = VERT + "ok" + RAZ if code and 200 <= code < 300 else JAUNE + str(code) + RAZ
        print(f"  {etat:12} {ms:5} ms   {nom}")
    print(f"\n{GRIS}Aucune ecriture n'a ete faite. Les routes POST ont ete volontairement"
          f"\nexclues : elles agissent sur une chaine comptable reelle.{RAZ}\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
