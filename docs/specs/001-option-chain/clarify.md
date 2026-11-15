# Clarify: decisioni aperte per l'operatore

2026-11-12. Revisione delle ambiguità della [specifica](spec.md), senza risposte presunte.
Repo privo di Speckit: non eseguiti script `.specify/`, non modificata infrastruttura.
Copertura esaminata: ambito, modello dati, lifecycle, guasti, integrazioni, qualità, licenza e costi.
Le cinque domande sono ordinate per impatto; le proposte restano esplicitamente provvisorie.

1. **Universo e uso:** bastano opzioni inverse settlement BTC/ETH e pannello interno, oppure includere anche lineari USDC su BTC/ETH o distribuzione a terzi?
   Proposta: inverse e uso interno; aggiungere USDC cambia discovery, unità, conversioni e dimensionamento.
   Risposta: aperta. Impatto: ambito, schema e licenza; requisito FR2.

2. **Cadenza/capacità:** approvare snapshot 60 s, summary 5 min, raw 7 giorni e normalizzati senza cancellazione automatica, con quale budget disco massimo?
   Alternative: persistenza 5 min per ridurre circa 5× le righe oppure archivio tiered dopo misurazione; non è dimostrata una precisione equivalente.
   Proposta: 60 s per intraday, misura preventiva del volume e nessuna cancellazione finché non decisa.
   Risposta: aperta. Impatto: storage e operatività; sezione cadenza/retention.

3. **Storico/licenza:** iniziare dallo storico nuovo gratuito o valutare acquisto Tardis; quali periodo, budget e utenti devono essere coperti?
   Proposta: nessun acquisto ora; campioni gratuiti possono aiutare la valutazione, non riempiono la serie.
   Richiedere conferma di campi, incidenti e applicabilità delle restrizioni Coinbase a Deribit prima di uso ML/redistribuzione.
   Risposta: aperta. Impatto: backfill e disponibilità point-in-time; FR9.

4. **Semantica analitica:** confermare skew put-minus-call, delta spot/forward/premium-adjusted e proxy GEX/DEX lordi (somma dei contributi assoluti), oppure con segno long-option-OI, con età OI per osservazione visibile?
   Proposta: greche fonte conservate, esposizione lorda senza compensazione call/put; variante con segno distinta, netto dealer non disponibile dall’OI; conversione USD esplicitamente validata prima di calcolo.
   Nessuna fonte consultata rivela il lato dealer; una misura dealer-signed richiederebbe ipotesi ulteriori approvate.
   Risposta: aperta. Impatto: contratto del pannello e controllo unità.

5. **Qualità nel pannello:** visualizzare snapshot parziali con elenco mancanti e proxy a età mista oppure rendere indisponibili i derivati finché la catena è completa?
   Proposta: conservare sempre dati/coverage; mostrare qualità ed età, con derivati non calcolabili esplicitamente indisponibili.
   Soglie di allarme operative sono separate dalle stime adattive dei derivati e richiedono un criterio di servizio approvato.
   Risposta: aperta. Impatto: accettazione scenari 1–4 e integrazione operator-console 008.

Non sono check rinviati della PR: sono decisioni di prodotto richieste per la futura implementazione.
La raccolta e il deploy restano fuori da questa consegna; nessun acquisto autorizzato.
