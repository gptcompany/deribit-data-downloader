# Specifica 001: snapshot catena opzioni Deribit

Stato: proposta per l'operatore, 2026-11-12; domande [Q1–Q5](clarify.md) aperte.
Flusso: ricerca → specifica → revisione delle ambiguità; Speckit non inizializzato nel repo.
Evidenze e limiti: [research.md](research.md). Nessuna implementazione autorizzata da questa specifica.

## Problema, utenti e confini

Il pannello operator-console spec 008 / PR #41 richiede skew, butterfly, GEX e DEX BTC/ETH.
Il servizio attuale raccoglie trades e DVOL, non lo stato completo della catena.
Baseline riferita da B5 sul Dell il 2026-11-12: catalogo `/media/sam/2TB-NVMe/data/deribit_options`, ultimo dato 06:01Z, run riuscito, timer giornaliero e freschezza oraria; non rieseguito qui.
L'operatore deve vedere origine, unità, copertura ed età di ogni misura.
Il ricercatore deve riprodurre ciò che era conoscibile allora, senza lookahead.
Ambito iniziale proposto: opzioni inverse con settlement BTC ed ETH, tutte le scadenze/strike/call/put.
Opzioni lineari USDC, ordini, posizioni private, acquisti di dataset, deploy e segnali di trading sono fuori ambito; Q1 conferma l'universo.

## Scenari e accettazione

1. Catena normale → ogni slot ha righe per l'universo atteso e un record di copertura; mark/IV/greche e OI hanno età distinte.
2. Connessione interrotta → slot mancanti espliciti; alla riconnessione seed completo, senza riempire il passato con stato nuovo.
3. Contratto creato/scaduto/halted → metadata versionati e lifecycle aggiornano il denominatore; assenza non equivale a OI zero.
4. Payload non valido, 429 o 10028 → quarantena/retry secondo fonte; nessuna pubblicazione come snapshot completo.
5. Crash durante write → solo file completi visibili; manifest/checkpoint permettono replay idempotente, senza duplicare la chiave logica.
6. Backtest a tempo T → nessuna riga con `received_at > T`, anche se `source_timestamp < T`; storico di terzi separato e riconoscibile.

La futura implementazione dimostra questi scenari in CI con fixture registrate e versionate prive di credenziali.
Le prove devono includere OI zero contro OI mancante, gamma e dimensioni BTC/ETH, IV percentuale contro frazione e replay di update parziali.
Questa PR non aggiunge test documentali: **Controprova: non applicabile: solo documentazione**.

## Requisiti funzionali

- FR1: usare API pubbliche ufficiali produzione; dichiarare hostname, metodo/canale e versione schema per ogni acquisizione.
- FR2: seed `get_instruments(kind=option)` per BTC/ETH e sottoscrizione lifecycle; conservare strumenti inattivi con stato esplicito.
- FR3: consumare ticker con greche, a intervallo pubblico disponibile; batching entro limiti pubblicati. Non richiedere feed raw autenticati implicitamente.
- FR4: ricostruire update incrementali solo dopo seed completo; i campi omessi mantengono timestamp dell'ultimo vero aggiornamento, non quello del messaggio.
- FR5: riconciliare summary per valuta e metadata dopo riconnessione; distinguere snapshot raccolto da una vista atomicamente simultanea, che la fonte non garantisce.
- FR6: non sostituire valori mancanti con zero, DVOL, ultima trade-IV o interpolazione non dichiarata.
- FR7: checkpoint dopo persistenza e manifest; eventuali file orfani si riconciliano da hash/chiavi senza cancellare dati validi.
- FR8: pubblicare snapshot parziale con coverage e cause; avanzare `last_complete_snapshot` solo quando tutti gli strumenti attesi sono rappresentati validamente.
- FR9: dati di terzi entrano con provider/licenza/periodo/campi e timestamp di disponibilità; mai riscrivere la provenienza come Deribit raccolto direttamente.

## Cadenza e retention proposte, da confermare Q2

Snapshot normalizzato ogni **60 secondi UTC**, da stream; summary REST ogni **5 minuti** e dopo riconnessione, metadata all'avvio/lifecycle.
Motivo: ticker incrementale ufficiale può aggiornare al secondo; 60 s conserva dinamica intraday senza N richieste REST/minuto, mentre il timer giornaliero attuale perde la struttura intraday.
Cinque minuti è un compromesso operativo proposto per riconciliare lo stream; non è una stima misurata di errore né un limite analitico.
Non promettere precisione subminuto dalla sola tabella normalizzata; eventi raw conservano la risoluzione ricevuta.
Retain raw compressi **7 giorni**, normalizzati e metadata **senza cancellazione automatica** inizialmente: OI/greche perse non sono ricostruibili da fonte ufficiale.
Sette giorni raw coprono un ciclo operativo settimanale di diagnosi, non un lookback per indicatori.
Dimensionamento esplicito: con N strumenti attivi medi, righe/giorno = `1440 × N`; byte/giorno = righe × byte compressi misurati/riga + raw misurati.
GET pubblico di ricerca 2026-11-12: BTC 926 ed ETH 762 strumenti, tutti active, N=1.688 in quel momento; inventario variabile, non limite superiore.
A quell'N: 2.430.720 righe/giorno; ipotizzando 200 byte compressi/riga, circa 486 MB/giorno e 177 GB/anno normalizzati; byte/riga non misurati, raw esclusi.
Prima del rollout misurare N, dimensione e traffico in CI/ambiente autorizzato; operatore approva budget, retention e spazio disponibile.
Se capacità insufficiente: segnalare e fermare nuove scritture in modo osservabile, senza cancellazioni silenziose o retention implicita.
Questi intervalli sono politiche di acquisizione/storage versionate, non soglie/lookback dei derivati.

## Schema logico v1

Una riga per `(provider, environment, currency, snapshot_slot, instrument_name, schema_version)`; timestamp UTC in millisecondi, numeri finiti nullable.

| Gruppo | Campi e semantica obbligatori |
|---|---|
| Identità | schema_version, provider, environment, currency, instrument_name, metadata_version/hash, snapshot_slot |
| Tempi | `timestamp` = slot per manifest; received_at, source_timestamp nullable, snapshot_started_at/completed_at; last-update per gruppo di campi |
| Contratto | strike, expiration_timestamp, option_type C/P, instrument_type, state, base/quote/settlement_currency, contract_size, price_index |
| Prezzi | bid_price, ask_price, mark_price, underlying_price, underlying_index; unità/native currency conservate, USD conversion separata e tracciata |
| Volatilità | bid_iv, ask_iv, mark_iv in frazione annua; valore percentuale originale preservato nei raw; null diverso da 0 |
| Greche | delta, gamma, vega, theta, rho native e convenzione/unità fonte; greeks_received_at e ultimo timestamp noto |
| Interesse aperto | open_interest, oi_unit = base currency per queste opzioni; oi_delay_ms = 28.800.000, oi_effective_at nullable e qualità della stima |
| Provenienza/qualità | endpoint/channel, raw hash/reference finché retained, collection_method, field_status, stale/missing reasons |

Metadata e slot coverage sono tabelle separate, versionate: expected/received/valid/missing counts, strumenti mancanti, motivo, complete, tempi e versione universo.
Non memorizzare chiavi, credenziali o valori di topic configurativi nei documenti/manifest.
Validazione tramite schema rigoroso Pydantic/PyArrow esistente esteso; unità e stato validati al confine, non regex sulle righe.

## Età dichiarata per fonte e campo

| Fonte/campo | Età esposta al consumatore |
|---|---|
| Ticker prezzi/IV/greche | `now - last_source_update` se noto; anche `now - received_at`; mai una SLA di freschezza implicita |
| Summary OI e ticker OI | Ritardo fonte 8 h più età dall'osservazione; `effective_at = observation - 8h` solo stima, non timestamp effettivo garantito |
| get_instruments | Cache circa 1 min più tempo dall'acquisizione; lifecycle separato, nessuna supposizione che metadata sia tick-live |
| Trades storici/esistenti | Timestamp evento e pubblicazione distinti; alcuni RFQ ritardati fino a 8 h, timestamp cursor da solo non prova completezza |
| DVOL | Risoluzione candela, timestamp e tempo acquisizione; fonte aggregata, non sostituto di skew |
| Fornitore storico | Timestamp exchange e disponibilità locale se forniti; in assenza, disponibilità storica non verificata e uso point-in-time non certificato |

## Catalogo, recovery e osservabilità

Root esistente parametrico, default documentato sopra; nuovi path `<currency>/chain/YYYY-MM-DD/` con shard immutabili, metadata separati; nessuna riscrittura di trades/DVOL.
Riutilizzare scrittura atomica e manifest esistenti; serializzare aggiornamenti del manifest condiviso tra job giornaliero e collector.
Checkpoint chain separato per valuta/sessione: ultimo slot persistito, universo e riferimenti file; non usare il cursore trades.
Esporre metriche per valuta: last_received, last_complete_snapshot, last_persisted_slot, source age per gruppo, OI delay, coverage, reconnect, missing slots, quarantine, write failures e capacità.
Riutilizzare `write_metrics`; aggiornare monitoraggio ogni slot persistito. L'exporter deve avere un writer coordinato per non eliminare le metriche trades/DVOL.
Un processo vivo o una metrica riscritta non dimostrano dati freschi; monitorare timestamp dell'ultimo avanzamento e ritardo strutturale separatamente.
Configurazione unica versionata con root/capacità come variabili documentate; nessun file host-specific o `.env` generato nel repo.

## Contratto per i derivati e pilastri nautilus_dev

La raccolta conserva osservazioni; il consumatore sceglie il modello, con versione e convenzioni esplicite.
Skew25 = `IV_put(abs(delta)=0,25) - IV_call(delta=0,25)`; positivo significa put più cara. Butterfly25 = media delle due IV25 meno IV ATM, con definizione ATM dichiarata.
Non copiare l'incoerenza di segno nella spec 042; delta spot/forward/premium-adjusted va deciso in Q4.
Interpolazione solo nel dominio coperto; altrimenti risultato indisponibile con motivo. Nessuna extrapolazione nascosta.
Per greche USD coerenti per unità base, proxy gross GEX USD per movimento 1% = `sum(gamma_USD × OI_base × S_USD² × 0,01)`; DEX USD = `sum(delta_USD × OI_base × S_USD)`.
Sono esposizioni nozionali dell'OI, non posizionamento dealer: segno dealer non osservato; put non implica automaticamente gamma negativa.
Non moltiplicare ancora per contract_size quando OI è già in base coin. Non applicare queste formule alle greche native senza verificare conversione e sensibilità inverse.
Prezzi/greche correnti + OI ritardato devono chiamarsi proxy a età mista; non «GEX live». Una vista allineata usa storico proprio e stima OI esplicita, senza anticiparne la disponibilità.
P1: riportare incertezza/copertura, non un numero privo di qualità; P2: modelli non lineari e code pesanti, senza normalità assunta.
P3: stima/adattamento online di filtri e finestre nei derivati, nessun lookback o soglia fissi importati dalla 042.
P4: confronti tramite rapporti/quantità adimensionali e valutazione di ensemble; 25-delta e unità 1% sono definizioni, non soglie di segnale.
Scegliere QuantLib solo se la superficie SVI è richiesta e validata; nessuna calibrazione o nuova libreria necessaria per salvare la catena.

## Decisioni e verifica della specifica

Assunzioni provvisorie: universo inverse BTC/ETH, raccolta pubblica senza chiavi, pannello interno, nessuna licenza esterna acquistata.
Q1–Q5 restano aperte: nessuna risposta inventata; non avviare implementazione prima che budget/licenza/convenzioni siano decisi.
Ricerca → verifica: URL primari e codice base consultati; specifica → verifica: scenari, schema, tempi e riuso incrociati; clarify → verifica: ogni ambiguità critica ha domanda numerata.
Nessun test/build locale eseguito per vincolo dell'operatore; CI della PR osservata nel body.
