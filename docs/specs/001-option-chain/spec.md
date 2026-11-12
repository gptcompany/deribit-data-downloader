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
Test documentali RED → GREEN: **non applicabile: solo documentazione**; il repo non prevede un runner documentale e la CI esclude Markdown/docs.
Controprova documentale osservata prima della correzione: review `rv-dr9` sulla head `ea180804…`, M1 DEX signed 0 USD contro lordo 500.000 USD; M2 storico 12:00 UTC trasformato erroneamente in 04:00 UTC.
Le definizioni e gli esempi sotto correggono queste contraddizioni; non sono test applicativi eseguiti.

## Requisiti funzionali

- FR1: usare API pubbliche ufficiali produzione; dichiarare hostname, metodo/canale e versione schema per ogni acquisizione.
- FR2: seed `get_instruments(kind=option)` per BTC/ETH e sottoscrizione lifecycle; conservare strumenti inattivi con stato esplicito.
- FR3: consumare ticker con greche, a intervallo pubblico disponibile; batching entro limiti pubblicati. Non richiedere feed raw autenticati implicitamente.
- FR4: ricostruire update incrementali solo dopo seed completo; i campi omessi mantengono timestamp dell'ultimo vero aggiornamento, non quello del messaggio.
- FR5: riconciliare summary per valuta e metadata dopo riconnessione; distinguere snapshot raccolto da una vista atomicamente simultanea, che la fonte non garantisce.
- FR6: non sostituire valori mancanti con zero, DVOL, ultima trade-IV o interpolazione non dichiarata.
- FR7: checkpoint dopo persistenza e manifest; eventuali file orfani si riconciliano da hash/chiavi senza cancellare dati validi.
- FR8: pubblicare snapshot parziale con coverage e cause; avanzare `last_complete_snapshot` solo quando tutti gli strumenti attesi sono rappresentati validamente.
- FR9: dati di terzi entrano con provider/licenza/periodo/campi e timestamp di disponibilità e tempi/ritardi per campo e osservazione (noti, stimati o sconosciuti); mai riscrivere la provenienza come Deribit raccolto direttamente.

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
| Tempi | `timestamp` = slot per manifest; received_at = acquisizione nostra, source_timestamp nullable = timestamp messaggio fonte, snapshot_started_at/completed_at; per campo ultimo source/received/effective_at e relativa qualità |
| Contratto | strike, expiration_timestamp, option_type C/P, instrument_type, state, base/quote/settlement_currency, contract_size, price_index |
| Prezzi | bid_price, ask_price, mark_price, underlying_price, underlying_index; unità/native currency conservate, USD conversion separata e tracciata |
| Volatilità | bid_iv, ask_iv, mark_iv in frazione annua; valore percentuale originale preservato nei raw; null diverso da 0 |
| Greche | delta, gamma, vega, theta, rho native e convenzione/unità fonte; greeks_received_at e ultimo timestamp noto |
| Interesse aperto | open_interest, oi_unit = base currency per queste opzioni; oi_source_timestamp, oi_received_at, oi_effective_at nullable; oi_delay_ms nullable = oi_received_at − oi_effective_at; oi_source_delay_ms nullable = oi_source_timestamp − oi_effective_at; delay_status observed/estimated/unknown, fonte/regola/periodo della stima |
| Provenienza/qualità | endpoint/channel, raw hash/reference finché retained, collection_method, field_status, stale/missing reasons |

Metadata e slot coverage sono tabelle separate, versionate: expected/received/valid/missing counts, strumenti mancanti, motivo, complete, tempi e versione universo.
Non memorizzare chiavi, credenziali o valori di topic configurativi nei documenti/manifest.
Validazione tramite schema rigoroso Pydantic/PyArrow esistente esteso; unità e stato validati al confine, non regex sulle righe.

## Età dichiarata per fonte e campo

| Fonte/campo | Età esposta al consumatore |
|---|---|
| Ticker prezzi/IV/greche | `now - last_source_update` se noto; anche `now - received_at`; mai una SLA di freschezza implicita |
| Summary OI e ticker OI | Per osservazione: `now - oi_effective_at` se noto/stimato, separato da `now - oi_received_at`; stato e origine del tempo esposti. Solo feed pubblico soggetto alla release 10 novembre: ritardo fonte stimato 8 h |
| get_instruments | Cache circa 1 min più tempo dall'acquisizione; lifecycle separato, nessuna supposizione che metadata sia tick-live |
| Trades storici/esistenti | Timestamp evento e pubblicazione distinti; alcuni RFQ ritardati fino a 8 h, timestamp cursor da solo non prova completezza |
| DVOL | Risoluzione candela, timestamp e tempo acquisizione; fonte aggregata, non sostituto di skew |
| Fornitore storico | Tempi per campo, periodo e provider; conservare timestamp exchange/effective e disponibilità originale se forniti, distinti dall’import nostro. Ritardo non verificabile = null/unknown, mai 8 h di default; point-in-time non certificato senza disponibilità originale |

`source_timestamp` del messaggio non certifica il tempo effettivo di ciascun campo. Per OI pubblico nel periodo soggetto alla release, in assenza di tempo effettivo esplicito, `oi_effective_at = oi_source_timestamp − 28.800.000` è una stima documentata; senza source timestamp verificabile resta null/unknown.
`oi_delay_ms` misura l’età all’acquisizione, incluso trasporto/backfill; `oi_source_delay_ms` separa il ritardo della fonte. Ogni campo mantiene i propri tempi anche negli update parziali; non attribuire il ritardo OI a prezzi/greche.
Esempio storico sintetico: fonte/tempo effettivo 2026-11-09 12:00 UTC, provider dichiara ritardo fonte 0 → conservare 12:00 UTC e `oi_source_delay_ms = 0`; un import il 13 novembre registra l’acquisizione del 13 e la corrispondente età, senza sottrarre 8 h. Se il ritardo originario non è verificabile, non inventare né zero né otto ore.

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
Per greche USD coerenti per unità base, porre `d_i = delta_USD_i × OI_base_i × S_USD` (USD) e `g_i = gamma_USD_i × OI_base_i × S_USD² × 0,01` (USD di variazione del delta nozionale per rialzo spot 1%).
Convenzione long-option-OI: OI non negativo conta una volta il lato long di ogni contratto; delta call positivo/put negativo, gamma long positivo per entrambe; il lato short inverte entrambi i segni. Fonti: [Deribit, delta](https://insights.deribit.com/education/introduction-to-option-greeks/) e [OIC, gamma](https://www.optionseducation.org/advancedconcepts/gamma), consultate 2026-11-13. Le formule aggregate seguenti sono definizioni proposte qui, non campi ufficiali Deribit.

| Misura proposta | DEX USD | GEX USD per rialzo 1% | Significato |
|---|---|---|---|
| Lorda (gross) | `sum(abs(d_i))` | `sum(abs(g_i))` | Nessuna compensazione tra contributi |
| Con segno, proxy long-option-OI | `sum(d_i)` | `sum(g_i)` | Call/put si compensano in DEX; gamma long non cambia segno per le put |
| Netta di portafoglio/dealer | `sum(delta_USD_i × q_i × S_USD)` | `sum(gamma_USD_i × q_i × S_USD² × 0,01)` | Richiede quantità base firmata `q_i`, positiva long/negativa short, del portafoglio scelto; non ricavabile dall’OI pubblico |

Con spot 100.000 USD, OI call/put 10 BTC ciascuno e delta +0,25/−0,25: DEX con segno = 0 USD, DEX lordo = 500.000 USD. Non etichettare il primo come lordo o netto dealer.
Per gamma long, GEX con segno e lordo coincidono; assegnare gamma negativa alle put sarebbe un’ulteriore ipotesi di posizionamento, non una proprietà della put. Q4 mantiene aperta la scelta del consumatore.
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
