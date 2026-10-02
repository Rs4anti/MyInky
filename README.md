# MyInky

Applicazione locale per configurare contenuti e pianificazione di un display e-paper Waveshare 4.2" V2 (400 x 300). La versione corrente mantiene l'orologio e il mock esistenti e aggiunge persistenza SQLite, plugin visuali, scheduler APScheduler, configurazione meteo Open-Meteo/OpenWeatherMap e cache offline.

## Stato attuale

- `GET /health`: stato dell'applicazione e modalità display.
- `GET /api/preview`: restituisce senza effetti collaterali l'ultimo frame applicato con successo; prima del primo aggiornamento mostra una preview del plugin pianificato. `current.png` viene aggiornato solo dopo un invio display riuscito.
- `GET /`: pagina locale con l'anteprima.
- `/settings/plugins`: attivazione plugin e intervalli distinti di aggiornamento contenuti e rotazione display.
- `/settings/weather`: provider, località/coordinate, timezone, unità, lingua e API key opzionale.
- `/photos`: libreria, impostazioni di elaborazione e sequenza del `PhotoPlugin`.
- `/photos/upload`: upload multiplo di immagini JPEG, PNG e WEBP.
- Modalità `mock` predefinita; modalità `waveshare` disponibile su Raspberry Pi OS con driver e SPI funzionanti, con fallback automatico a mock.
- `Waveshare4In2V2Display` usa l'API ufficiale `epd4in2_V2.EPD`; le capability fast/partial sono rilevate dai metodi presenti nel driver.
- `/display`: diagnostica driver/hash e comandi manuali refresh, clear e sleep.
- L'immagine inviata al mock è PIL `1` (bianco e nero) e viene scritta atomicamente.
- SQLite conserva `Settings`, `PluginSettings`, `DisplayState` e l'ultima cache meteo valida.
- `ClockPlugin`, `WeatherPlugin` e `PhotoPlugin` con libreria immagini.
- Refresh contenuti indipendente dalla rotazione: Clock aggiorna i dati ogni 1 min, Weather aggiorna la cache ogni 30 min; ogni plugin resta visibile per la rotazione configurata (10 min iniziali).
- Scheduler eseguibile come processo separato, con lock file, job non concorrenti e reload della configurazione salvata.
- Provider meteo senza chiamate HTTP durante il rendering; in assenza di rete usa la cache persistita.

Open-Meteo è il provider predefinito e non richiede una chiave. Le chiavi OpenWeatherMap sono cifrate con Fernet e una chiave locale in `data/secrets/`; proteggi la directory dati e non copiarla in backup condivisi. La UI non restituisce né mostra la chiave.

Non pubblicare il servizio direttamente su Internet.

## Requisiti

- Python 3.11 o superiore.
- `bash` per `scripts/install.sh` su Raspberry Pi OS/Debian.
- `make` opzionale per i comandi abbreviati.

## Installazione e sviluppo

Su Raspberry Pi OS o Linux con Python 3.11+:

```bash
bash scripts/install.sh
source .venv/bin/activate
python run.py
```

Lo script crea `.venv/` solo se non esiste, aggiorna pip, setuptools e wheel, installa i requisiti runtime e di sviluppo e verifica import e dipendenze. Se `.venv` esiste ma non è utilizzabile, lo script si ferma con un errore invece di eliminarlo.

In alternativa, con GNU Make:

```bash
make venv
make install
make dev
```

`make dev` avvia un server e un solo scheduler nel processo di sviluppo. `python run.py` fa lo stesso. In produzione, scegli un web server senza scheduler incorporato e avvia esattamente un processo `make scheduler` (o `python run_scheduler.py`). Non eseguire `run.py` insieme a `run_scheduler.py`: il lock di processo impedisce la seconda istanza. I job hanno ID stabili, vengono sostituiti senza duplicarsi e i reload invariati conservano la prossima scadenza.

I target `lint`, `test` e `check` eseguono Ruff, Black, mypy e pytest. `make install`, `make lint`, `make test`, `make check`, `make dev` e `make scheduler` creano `.venv` se manca e installano i requisiti. Su Windows PowerShell si può preparare e avviare il venv manualmente:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run.py
```

L'app si avvia per impostazione predefinita su `http://127.0.0.1:5000`; per una LAN è configurata su `0.0.0.0:5000`. Il server integrato è solo per sviluppo: non esporre il servizio direttamente su Internet.

## Configurazione

Copia `.env.example` in `.env` se vuoi impostare valori locali. Le variabili supportate in questa fase sono:

| Variabile | Default | Descrizione |
| --- | --- | --- |
| `INKDISPLAY_HOST` | `0.0.0.0` | Indirizzo di ascolto |
| `INKDISPLAY_PORT` | `5000` | Porta TCP, da 1 a 65535 |
| `INKDISPLAY_TIMEZONE` | `Europe/Rome` | Timezone IANA usata per l'orologio |
| `INKDISPLAY_DISPLAY` | `mock` | `mock` oppure `waveshare` |
| `INKDISPLAY_DATA_DIR` | `data` | Directory dei preview generati |
| `INKDISPLAY_SECRET_KEY` | casuale per processo | Chiave Flask; impostala a un valore casuale stabile quando si aggiungeranno le sessioni |

Le timezone IANA sono fornite dal pacchetto `tzdata`, così `Europe/Rome` funziona anche su Windows senza database timezone di sistema.

## Verifica Hardware

Target verificato: Waveshare e-Paper 4.2" V2, 400×300, B/W. Il collegamento SPI a 40 pin documentato da Waveshare è:

| Display | Raspberry Pi |
| --- | --- |
| VCC | 3.3V, pin fisico 1 |
| GND | GND, pin fisico 6 |
| DIN | MOSI / GPIO10, pin 19 |
| CLK | SCLK / GPIO11, pin 23 |
| CS | CE0 / GPIO8, pin 24 |
| DC | GPIO25, pin 22 |
| RST | GPIO17, pin 11 |
| BUSY | GPIO24, pin 18 |

Controlla la revisione del driver board e segui il manuale ufficiale per l'alimentazione. Non applicare 5V ai GPIO Raspberry Pi; collega GND comune e non alimentare contemporaneamente il pannello da fonti non previste.

Abilita SPI con `sudo raspi-config` → Interface Options → SPI → Enable, poi riavvia. Verifica il device:

```bash
ls /dev/spidev*
```

Installa i prerequisiti nel virtual environment e scarica il repository driver ufficiale Waveshare:

```bash
sudo apt update
sudo apt install -y python3-dev
git clone --depth 1 https://github.com/waveshare/e-Paper.git ~/e-Paper
source .venv/bin/activate
python -m pip install RPi.GPIO spidev
export PYTHONPATH="$HOME/e-Paper/RaspberryPi_JetsonNano/python/lib${PYTHONPATH:+:$PYTHONPATH}"
python -c "from waveshare_epd import epd4in2_V2; epd = epd4in2_V2.EPD(); print(epd.width, epd.height); epd.init(); epd.Clear(); epd.sleep()"
```

Il test precedente inizializza, cancella e mette in sleep il pannello: eseguilo solo con cablaggio verificato. Imposta quindi `INKDISPLAY_DISPLAY=waveshare` in `.env` e riavvia il servizio/app. La UI `/display` mostra modalità effettiva, driver e capability. Se il processo non è su Raspberry Pi o il modulo/API non sono disponibili, viene emesso un warning e l'app resta in modalità mock. Per systemd, imposta `PYTHONPATH` nell'unità con `Environment=PYTHONPATH=/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib`; python-dotenv è caricato dopo l'avvio dell'interprete e non può impostare il path degli import retroattivamente.

Il codice adapter usa solo i metodi verificati nel driver ufficiale: `init`, `ReadBusy`, `getbuffer`, `display`, `Clear`, `sleep`, `init_fast`, `display_Fast` e `display_Partial`. Fast/partial risultano disponibili solo se il driver espone l'intero gruppo di metodi richiesto. Clock richiede partial tramite metadata immagine; il wrapper fa fallback full se non supportato e forza un full dopo cinque partial consecutivi per ridurre ghosting. Le schermate meteo/foto richiedono full.

Troubleshooting: se `waveshare_epd` manca, verifica `PYTHONPATH` e il clone ufficiale; se GPIO non è disponibile, controlla `RPi.GPIO` e avvia come utente con accesso ai GPIO; se SPI manca, verifica `/dev/spidev*`, `raspi-config` e che il bus non sia occupato. Un errore all'avvio seleziona il mock; un errore hardware runtime viene registrato e commuta automaticamente al mock, senza dichiarare riuscito il plugin non applicato. Se BUSY resta alto, verifica cablaggio BUSY/RST, alimentazione e SPI; il driver ufficiale attende BUSY internamente. Se il pannello resta bianco o mostra artefatti, controlla VCC/GND, ordine dei pin, versione V2 e usa prima il test ufficiale completo. Dopo sleep il driver viene reinizializzato alla prossima operazione.

Le impostazioni di contenuto vengono salvate nel database in `data/inkdisplay.sqlite3` e sopravvivono al riavvio. I modelli SQLAlchemy sono gestiti anche da Flask-Migrate; per inizializzare/aggiornare lo schema:

```bash
python -m flask --app run db upgrade
```

Le migration sono additive. Prima di avviare una versione aggiornata su un database esistente, esegui `python -m flask --app run db upgrade`; le nuove colonne DisplayState non eliminano né riscrivono i dati legacy.

## Plugin e pianificazione

Apri `/settings/plugins`. Il refresh interval aggiorna contenuti/cache ma non cambia plugin; il rotation interval è la durata di permanenza a schermo. Con rotazione a 10 minuti Clock resta visibile per 10 minuti, poi Weather per 10 minuti, quindi Photo se abilitato e con almeno una foto attiva. Un refresh Clock/Weather ridisegna quel plugin solo se è già corrente. Solo rotazione o il comando manuale “Prossimo plugin” cambiano la playlist. Refresh corrente non azzera la scadenza; Next avanza una volta e riparte con una nuova durata.

Clock usa un frame bianco senza banner, con ora grande, data italiana centrata e timezone discreta. Formato 12/24 ore, secondi, timezone e riepilogo meteo in cache sono configurabili nei parametri Clock; i secondi restano nascosti quando il refresh è almeno un minuto. Clear pulisce il pannello ma lascia invariata la playlist.

L'ultimo plugin mostrato e il timestamp vengono salvati in `DisplayState`; dopo il riavvio la rotazione riprende dal plugin successivo nell'ordine persistito. Se non è disponibile alcuna cache meteo, il plugin mostra un layout offline informativo.

## Configurazione meteo

Apri `/settings/weather` per scegliere Open-Meteo oppure OpenWeatherMap e impostare coordinate o città, timezone, unità e lingua. La cache SQLite viene aggiornata secondo il refresh interval di WeatherPlugin (30 minuti predefiniti); un errore del provider mantiene disponibile lo snapshot precedente e il renderer marca i dati scaduti. Le richieste usano timeout, retry limitati e User-Agent esplicito.

### Schermata e-paper

Il renderer riutilizzato produce un frame 400 x 300, PIL `1`, con priorità a una lettura rapida da distanza:

```text
+--------------------------------------+
| BRESCIA                       10:25  |
| Dati aggiornati 4 minuti fa          |
|       [icona meteo]       21 °C      |
|                          Sereno      |
| Umidità: 63%   Vento: 12 km/h         |
| Pressione: 1018 hPa                  |
| PROSSIMI 3 GIORNI                    |
| Dom 27 [icona]  Lun 28 [icona] ...   |
|       15° / 25°       14° / 24°      |
+--------------------------------------+
```

Le icone sono primitive Pillow monocromatiche scalabili: sole, sereno notturno, poco nuvoloso, nuvoloso, pioggia, temporale, neve e nebbia. Il renderer distingue i codici WMO e usa l'ora locale come fallback giorno/notte.

In `/settings/weather` si possono mostrare o nascondere umidità, vento, pressione, temperatura percepita e forecast. Queste opzioni sono persistite nel JSON già presente in `PluginSettings.parameters`, quindi non richiedono una modifica dello schema SQLite. L'header mostra l'ora dell'ultimo fetch; sotto compare l'età calcolata dal timestamp persistito e, quando lo snapshot proviene dalla cache scaduta, `OFFLINE - dati da cache` senza rimuovere il meteo.

Ogni render del `WeatherPlugin` aggiorna atomicamente `data/previews/weather-preview.png`. `data/previews/current.png` rappresenta invece l'ultimo frame inviato con successo, anche su hardware Waveshare; non viene sovrascritto dai refresh di contenuto o da GET di preview.

La temperatura percepita viene normalizzata in `WeatherSnapshot` dai campi `apparent_temperature` di Open-Meteo e `main.feels_like` di OpenWeatherMap quando disponibili. Il renderer omette la riga se il provider non fornisce il valore.

## Gestione foto

Apri `/photos` per visualizzare miniature elaborate, nome originale, dimensioni, peso, data upload e stato attivo. `/photos/upload` accetta upload multipli JPG/JPEG, PNG e WEBP. Il server controlla MIME dichiarato e formato Pillow reale, esegue `Image.verify()`, riapre l'immagine, corregge l'orientamento EXIF, applica un nome UUID e archivia l'originale in `data/uploads/`. Il limite configurabile è da 1 a 10 MB per file; immagini corrotte o decompression bomb vengono rifiutate.

Le foto attive entrano nel `PhotoPlugin` quando è abilitato “Includi foto nella rotazione”. Modalità sequenziale e casuale, adattamento, dithering, contrasto, nitidezza e ultimo ID mostrato sono conservati nel JSON del plugin già presente in `PluginSettings.parameters`; il solo schema aggiunto è la tabella `photos` con metadati, non contenuti immagine.

Adattamento disponibile: `contain` mantiene tutta la foto su fondo bianco, `cover` riempie il frame con ritaglio centrale, `center crop` ritaglia il centro prima del resize. Dithering: nessuno (soglia), Floyd-Steinberg e Atkinson. Il renderer applica correzione EXIF, RGB, resize/crop, contrasto, nitidezza, grayscale e conversione finale PIL `1` a 400×300.

Il plugin scrive automaticamente `data/previews/photo-preview.png`; `data/previews/current.png` continua a rappresentare l'ultima immagine inviata al mock display. L'anteprima elaborata generata durante i test è disponibile in [photo-preview.png](data/previews/photo-preview.png).

## Preview

Avvia l'app e apri `http://localhost:5000/` oppure `http://localhost:5000/api/preview`. La preview corrisponde all'ultimo frame applicato con successo, usa header `no-store` e non comanda il pannello. La dashboard aggiunge un token versione basato su hash/timestamp. Prima del primo successo viene renderizzato il plugin pianificato senza inviarlo all'hardware. `clock-preview.png` è la preview aggiornata atomicamente a ogni render del clock; `current.png` cambia solo dopo un'applicazione display riuscita.

### Font Clock Raspberry Pi

Il clock richiede un font TrueType di sistema: il font bitmap predefinito di Pillow non viene usato per l'ora. Il renderer preferisce DejaVu Sans Condensed Bold e registra in DEBUG il percorso assoluto del TTF caricato, il bbox e i pixel neri finali. Controlla i font disponibili sul Raspberry Pi:

```bash
fc-match "DejaVu Sans Condensed:style=Bold"
find /usr/share/fonts -iname "DejaVuSans*Bold.ttf"
```

Se non è installato un font TrueType adatto:

```bash
sudo apt update
sudo apt install -y fonts-dejavu-core
```

Se DejaVu è presente ma non raggiunge le soglie di pixel finali, installa anche il font condensato alternativo cercato dal renderer:

```bash
sudo apt install -y fonts-liberation
```

I font sono risorse di sistema e non vanno installati nel virtual environment Python.

## Dashboard e display

La dashboard distingue plugin pianificato, ultimo plugin realmente applicato, prossimo plugin, inizio e scadenza di permanenza, refresh contenuti, tentativo, successo, modalità ed hash. Mostra timestamp nella timezone configurata; se pianificazione e ultimo frame divergono, espone un avviso invece di presentarli come equivalenti. `/display` offre Refresh corrente, Prossimo plugin, Clear e Sleep; ogni comando usa il lock display condiviso e non crea job scheduler.

## Test e qualità

```bash
python -m ruff check .
python -m black --check .
python -m mypy inkdisplay
python -m pytest
python -m pytest --cov=inkdisplay --cov-report=term-missing
```

Oppure usa `make check`. I test usano il client Flask, directory temporanee e il mock: non richiedono rete, GPIO o hardware.

## Struttura

```text
inkdisplay/
  application/services/   casi d'uso
  config.py               configurazione e validazione
  infrastructure/display/ porta e mock display
  infrastructure/persistence/ modelli SQLite e bootstrap
  infrastructure/scheduler/ APScheduler con lock di processo
  infrastructure/weather/ provider e cache meteo
  presentation/rendering/ renderer Pillow indipendente dall'hardware
  presentation/web/       pagine impostazioni
  templates/              dashboard e navbar condivisa
migrations/               revisioni Flask-Migrate/Alembic
tests/
  unit/
  integration/
scripts/install.sh        bootstrap del venv su Linux
data/previews/            immagine prodotta dal mock
```

## Dipendenze

Flask e Requests sono distribuiti con licenza BSD-3-Clause, Flask-SQLAlchemy con licenza MIT, Pillow con licenza HPND, APScheduler con licenza MIT, cryptography con licenza Apache-2.0/BSD, e python-dotenv con licenza BSD-3-Clause. Flask-Migrate e Alembic sono MIT, Flask-WTF è BSD-3-Clause, SQLAlchemy è MIT, `filelock` è MIT e `tzdata` Apache-2.0. Le dipendenze di sviluppo pytest, pytest-cov, Ruff, Black e mypy sono MIT. Font e driver Waveshare non sono inclusi né scaricati.

Fonti ufficiali: [Flask](https://flask.palletsprojects.com/), [Pillow](https://pillow.readthedocs.io/), [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html), [Waveshare 4.2 e-Paper manuale](https://www.waveshare.com/wiki/4.2inch_e-Paper_Module_Manual), [Waveshare e-Paper driver](https://github.com/waveshare/e-Paper).