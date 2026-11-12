# Ricerca: catena opzioni BTC ed ETH

Data di consultazione: 2026-11-12. Base del codice: `356e5a56b7be591bd669c25384f679655fa3f514`.
Solo ricerca e specifica; nessun acquisto, codice applicativo o deploy.
Il repo non contiene `.specify/`: si usa il fallback `docs/specs/001-option-chain/`.
Non contiene neppure un template PR; il body usa il modello comune gbg-agents.

## Esito e limiti delle evidenze

La catena pubblica corrente permette IV, mark e greche, ma **dal 10 novembre 2026 OI è ritardato di otto ore**.
Non è documentato un replay ufficiale gratuito della catena completa passata.
Trades e DVOL non ricostruiscono OI, quote e greche di strumenti che non hanno scambiato.
Il download futuro costruisce pertanto uno storico nuovo; il backfill completo richiede altra fonte.
Le pagine API senza data editoriale sono evidenze consultate oggi, non prove della loro data di introduzione.

## Fonti ufficiali: acquisizione e cambiamenti

| Data dell'evento/documento | Fonte primaria | Riscontro e conseguenza |
|---|---|---|
| 2025-05-08 | [Coinbase risultati Q1, eventi successivi](https://s27.q4cdn.com/397450999/files/doc_financials/2025/q1/5289651d-49ea-44bb-b6cb-d142aef095e4.pdf) | Accordo per acquisire Deribit, soggetto ad approvazioni; annuncio, non completamento. |
| 2025-08-14; bilancio 2025 pubblicato nel 2026 | [Coinbase annual report, acquisizioni](https://www.sec.gov/Archives/edgar/data/1679788/000167978826000047/coinbase2025ars.pdf) | Acquisizione completata il 14 agosto 2025. |
| 2026-10-01; pagina senza data editoriale | [Guida ufficiale migrazione INTX](https://docs.deribit.com/articles/intx-api-migration) | Coinbase International Exchange consolidato in Deribit; chiavi INTX non trasferibili, endpoint Deribit; account Deribit preesistenti invariati. |
| 2026-11-10; aggiornato 2026-11-11 | [Release Deribit](https://support.deribit.com/hc/en-us/articles/40275495462301-10-November-2026) | OI pubblico HTTP/WS ritardato 8 h; OI realtime non più disponibile. RFQ qualificati pubblicati fino a 8 h dopo, con timestamp originale e fuori ordine. |

Le pagine autonome degli annunci Coinbase/Deribit non sono state recuperate: **non verificato** il loro testo.
Il completamento è verificato dal bilancio Coinbase, non inferito dal solo annuncio dell'accordo.
Nesso causale acquisizione → ritardo OI: **non verificato**.
Cambio o deprecazione di `history.deribit.com` dovuto all'acquisizione: **non verificato**.
Applicazione automatica dei termini market-data Coinbase ai dati Deribit: **non verificato**.
Non assumere che l'acquisizione autorizzi redistribuzione o uso ML dei dati.
[Termini market-data Coinbase](https://www.coinbase.com/legal/market_data), aggiornati 2026-08-07: restrizioni su uso esterno, benchmark e AI/ML; il testo consultato non identifica esplicitamente il perimetro Deribit.
La [release 2025-09-02](https://support.deribit.com/hc/en-us/articles/29871649513117-2-September-2025) depreca metodi legacy RFQ e sposta FIX su `fix.deribit.com`: non è una migrazione del downloader HTTP né prova di chiusura history.

## Endpoint e copertura

Produzione HTTP: `https://www.deribit.com/api/v2/`; WS: `wss://www.deribit.com/ws/api/v2`.
Testnet separata: `test.deribit.com`; non mescolare dati di prova e produzione.

| Metodo/fonte ufficiale | Disponibile | Limiti rilevanti |
|---|---|---|
| [public/get_book_summary_by_currency](https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency), `kind=option` | Intera valuta: mark, mark_iv, bid/ask, OI, underlying | Niente greche; OI 8 h; timestamp risposta non rende OI corrente. |
| [public/ticker](https://docs.deribit.com/api-reference/market-data/public-ticker) | Un contratto: mark/bid/ask IV, delta/gamma/vega/theta/rho, underlying, OI | Costo proporzionale al numero di strumenti; OI 8 h. |
| [public/get_instruments](https://docs.deribit.com/api-reference/market-data/public-get_instruments) | Strike, expiry, tipo, dimensione, valute, stato | Cache circa 1 min; `expired=true` solo delivered recenti, non archivio completo. `currency` filtra settlement, quindi BTC/ETH non include automaticamente USDC. |
| [Guida istituzionale, Historical Data](https://static.deribit.com/files/DeribitInstitutionalSetupGuide.pdf) | `history.deribit.com/api/v2/public/`: trades e metadati storici dal 2016; get_instrument(s), get_last_trades_* | Non documenta snapshot storici OI/greche. Limiti numerici del PDF possono differire dall'API corrente: non usarli come contratto runtime. |
| [public/get_mark_price_history](https://docs.deribit.com/api-reference/market-data/public-get_mark_price_history) | Mark storici a 5 minuti | Solo sottoinsieme di opzioni usate nell'indice volatilità; altri strumenti restituiscono lista vuota. Non dà OI/greche/superficie completa. |
| [public/get_volatility_index_data](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data) | DVOL storico aggregato | Non IV per strike; già acquisito dal progetto. |

### Frequenza e condizioni

[Rate limits](https://docs.deribit.com/articles/rate-limits), consultati 2026-11-12: anonimi per IP, quota numerica pubblica garantita **non verificata**.
Il pool autenticato non-matching documenta 20 richieste/s e burst 100; non è una garanzia per l'IP anonimo.
`get_instruments` ha limite distinto 1/s, burst 50; subscribe circa 3,3/s, burst 10.
Su `10028` attendere il ripristino crediti e riconnettere; gestire anche errori JSON-RPC dentro HTTP 200.
[API usage policy](https://docs.deribit.com/articles/api-usage-policy): fair use, throttling e possibili blocchi; sottoscrizioni fino a 500 canali per richiesta.
L'accessibilità pubblica non equivale a licenza aperta: permesso specifico di redistribuzione **non verificato**.
[Best practice ufficiale opzioni](https://docs.deribit.com/articles/options-data-collection-best-practices) raccomanda seed strumenti, eventi lifecycle e stream ticker; `markprice.options` non contiene greche.
Preferire stream con persistenza periodica, riconciliazione summary; evitare N ticker REST ogni minuto.
Misura di ricerca tramite GET pubblico `get_instruments(kind=option,currency=BTC/ETH)` il 2026-11-12: 926 BTC + 762 ETH, tutti active; N=1.688, dunque il polling ticker per strumento ogni minuto costerebbe circa 28 richieste/s prima dei retry.

## Storico alternativo: nessun acquisto autorizzato

| Fonte | Copertura, costo consultato 2026-11-12 | Licenza e decisione |
|---|---|---|
| [Tardis Deribit](https://docs.tardis.dev/historical-data-details/deribit) | Dal 2019-03-30; CSV `options_chain`, feed WS con timestamp locale. Primo giorno di ogni mese gratuito: campione discontinuo. | Copertura effettiva per campo/giorno e incidenti da controllare prima di acquistare. Non ripristina OI realtime dopo la restrizione della fonte. |
| [Tardis listino Options](https://tardis.dev/#pricing) | USD/mese: Academic 350 (fatturazione trimestrale/annuale), Solo 700, Professional 1.000, Business 3.000; tasse escluse. Piano e profondità storica dipendono dalla fatturazione. | [Termini aggiornati 2026-10-28](https://docs.tardis.dev/legal/terms-of-service): uso interno, restrizioni su redistribuzione e derivati; licenza dei dati distinta dal client open source. Clausola 23 Coinbase: applicabilità a Deribit **non verificata**, chiedere conferma scritta. |
| Amberdata / Kaiko, candidati commerciali | Prezzo, campi storici e profondità verificabili per questo task: **non verificato**; richiedono verifica e preventivo. | Licenza specifica e permessi per pannello/ML: **non verificato**. Nessuna raccomandazione d'acquisto su queste basi. |
| Raccolta propria da ora | Nessun canone API pubblico verificato; storage/gestione a carico nostro; nessun recupero delle ore perse. | Termini Deribit da rispettare; nessuna licenza aperta dedotta. |

## Riuso del codice al SHA base

Non serve un nuovo downloader generale: httpx, PyArrow, Pydantic e le primitive di persistenza esistono già.

| Componente esistente | Riuso senza modifica | Estensione necessaria per la catena |
|---|---|---|
| `fetcher.py` | Client HTTP, ritmo e backoff come primitive | Endpoint/costi distinti, JSON-RPC 10028; stream pubblico e riconnessione non esistono oggi. Ritmo fisso 0,1 s non basta come garanzia. |
| `checkpoint.py` | Pattern scrittura temporanea + rename | Stato snapshot separato da cursore trades; non fingere resume storico della catena. |
| `manifest.py` | Hash SHA256, size, row count, range della colonna `timestamp` | Nuovo namespace/schema; un solo writer per manifest, nessun lock concorrente esistente. |
| `storage.py` | `_atomic_write`: PyArrow, fsync, rename, compressione | Nuove tabelle/partizioni; conversioni trades/DVOL non riutilizzabili per le opzioni. |
| `dead_letter.py` | Pattern di registrazione JSONL | Envelope trade-specific da estendere; append non è una transazione snapshot. |
| `validator.py` | Tipi severity/issue/result | Regole e lettura sono trade-specific; nuovo validatore schema/unità/copertura, senza importare soglie analitiche fisse. |
| `freshness.py` | `write_metrics` atomico | Scan/render per chain completa, età per campo e ritardo OI; controllo orario attuale insufficiente per raccolta al minuto. |

Finding fuori implementazione: trades tardivi della release 10 novembre possono sfuggire al resume per solo timestamp in `fetcher.py`; segnalato al coordinatore, nessuna correzione in questa PR.
Letto prima il catalogo `/home/sam/orca/workspaces/gbg-agents/sup-b6-dell/docs/research/reuse-catalog.md`: nessuna voce dedicata riutilizzabile trovata per catena/greche/SVI.
Letti `nautilus_dev/specs/042-deribit-options-data/{spec,plan,tasks}.md` e costituzione: `research.md` assente sia nel checkout locale sia nell'elenco di origin/main via API GitHub.
Il piano 042 ricava IV dai trades: utile per trade-IV, insufficiente per catena/OI; non importarne filtri/lookback fissi.

## Librerie mantenute e scelta proposta

Stato GitHub via API al 2026-11-12, non archiviati; ultima push è evidenza di attività, non certificazione finanziaria.

| Repo e attività | Capacità/licenza | Confronto con scrittura propria |
|---|---|---|
| [QuantLib](https://github.com/lballabio/QuantLib), push 2026-11-12 | Pricing/greche e SVI (`ql/experimental/volatility/sviinterpolation.hpp`); licenza BSD modificata nel repo | Preferire per SVI se serve davvero, con binding Python; dipendenza C++ più pesante. Non implementare un ottimizzatore SVI nuovo. |
| [vollib/py_vollib](https://github.com/vollib/py_vollib), push 2026-05-29 | Black/Black-Scholes, IV e greche; MIT; README indica `vollib` come nome canonico da 1.0.7 e namespace `py_vollib` deprecato | Candidato leggero per controllo indipendente, non sostituisce le convenzioni inverse Deribit automaticamente. |
| [SciPy](https://github.com/scipy/scipy), push 2026-11-12 | Ottimizzazione/interpolazione; BSD-3-Clause | Riutilizzabile ma SVI scritto sopra richiede vincoli/no-arbitraggio e manutenzione propri; meno riuso di QuantLib. |

GEX/DEX richiedono una somma con unità e convenzione esplicite, non una nuova libreria finanziaria generale.
Nessun repo GEX specializzato mantenuto e con convenzioni Deribit verificato: non adottare formule retail con segno dealer presunto.
Prima usare greche ufficiali; eventuale ricalcolo deve distinguere sensibilità in USD da sensibilità del premio in coin.
SVI è opzionale nel consumatore: per la raccolta non serve alcuna nuova dipendenza quantitativa.
