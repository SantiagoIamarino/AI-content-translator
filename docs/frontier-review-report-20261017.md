# Revisión técnica independiente — doblaje ES→EN de gameplays

Fecha: 2026-10-17. Checkout revisado: `/home/siamarino/ai-dubbing-e2e-asr-batch1`,
rama `fix/asr-correctness-20261016`, HEAD `8eb4e4c`. Plan propuesto separado:
[frontier-review-plan-20261017.md](frontier-review-plan-20261017.md).

**Método y límites.** Revisión de solo lectura: código, documentación, Git y JSON
guardados de los jobs. No se modificó código, configuración, jobs ni cachés. No se
tomaron locks, no se invocaron proveedores ni modelos, no se sintetizó, no se
exportó, no se ejecutó la suite ni los helpers de evaluación. Las cifras nuevas
de este informe salen de lecturas puras de `manifest.json`, `schedule/summary.json`,
`report/*.json`, estados y respuestas de proveedor guardadas (scripts de una línea
con `python3 -B`, sin importar `aidub`). **No escuché audio.** Todo lo que diga
sobre lecturas ASR es evidencia de ASR, no verdad acústica. Las estimaciones de
recuperación, tiempo y costo están marcadas como **estimación**.

---

## 1. Resumen ejecutivo

**Dictamen.** Los batches 1–4, el aislamiento por cue (`186e5b2`) y el replay
determinista (`f904a3e`) acercan al objetivo y conviene conservarlos. La
resolución de fuente del batch 5, tal como quedó tras `79cdcfd`, es hoy **la
principal causa de pérdida de comentario** y la mayor fuente de complejidad.
Pide a un modelo de texto que "adjudique acústica" que no puede oír. Después, un
validador determinista rechaza casi todas sus respuestas por reglas formales.
Lo agravan tres cosas: la unidad de retención es el cue entero (hasta 28,9 s) y
no la frase dudosa, la ronda final puede revisar sin confirmar, y ningún test de
cobertura detectó la regresión.

Cifras clave sobre los mismos inputs guardados del job de 82 min:

- **107 de las 115 omisiones** son cues con una lectura alternativa del segundo
  pase ASR. Solo **17 de los 124** cues con alternativa llegaron a colocarse (14 %).
- De esas 107, **42 difieren solo por acentos/puntuación (4) o por palabras
  agregadas/faltantes en los bordes (38)**. Ese patrón es compatible con
  recortes de ventana del mismo Whisper turbo, aunque no prueba que no haya
  habla. Cuidado: el control de polaridad 234 también es un recorte de borde,
  así que "borde" no equivale a "inocuo".
- El proveedor devolvió **99 respuestas inválidas en 202 intentos (49 %)**.
  Los intentos de resolución de fuente suman 1.225 s de los 2.134 s de
  intervalos de comando.
- Entre las 73 omisiones "localizadas con contrato agotado", hay **53 cues
  (≈172,9 s de ventanas)** con cuatro condiciones a la vez: la revisión bilingüe
  normal aceptó el inglés viendo ambas lecturas ASR; *todas* las respuestas
  guardadas del revisor de fuente dijeron `supported`/`minor`; no hay diferencia
  de negación ni de número; y el inglés no cambió. Las retuvo solo el validador
  determinista. En otros 8 casos el revisor pasó a `material` recién después de
  recibir el feedback del validador. Es un incentivo perverso documentado.
- La corrida "desatendida" se detuvo a las 05:23 UTC y quedó parada hasta las
  14:09 UTC (≈8,8 h). Después hubo tres salidas más por handoff que requirieron
  relanzar a mano. Tiempo activo: 2,79 h. Wall total: 12,83 h.

**Recomendación concreta.** No avanzar con más ajustes de prompt ni de
presupuesto en `source_resolution`. Reemplazar su política de elegibilidad por
una **política v3 determinista y más simple**:

- El inglés aceptado por la revisión bilingüe normal, que ya ve ambas lecturas,
  es suficiente para diferencias léxicas no críticas.
- Las diferencias de negación o de número siguen retenidas salvo acuerdo
  acústico determinista.
- La disputa explícita del revisor, las revisiones sin confirmar y las
  abstenciones materiales siguen retenidas.

Cada cambio de política debe pasar una **compuerta de regresión de cobertura**
sobre el corpus guardado (821 + 21 cues) y un **gold set etiquetado una vez por
vos** (≈60 cues). Con eso:

1. **Recuperación inmediata** del job actual, sin llamadas nuevas y con
   migración explícita bajo lock. Se suman las 8 colocaciones demostradas, los
   8 elegibles pendientes de audio y los 53 cues de arriba, con un muestreo de
   escucha previo. **Estimación: 760–778/821 colocados** (hoy 706). Tiempo
   estimado de máquina: ~40–60 min más tu escucha.
2. **Para gameplays futuros:** retirar del camino productivo el bucle LLM de
   adjudicación acústica, las partes parciales (`supported_spans`) y la
   aceptación manual dirigida. Unificar la confirmación en la revisión normal,
   con una ronda final solo de confirmación. Segmentar en grupos de respiración
   antes de traducir. Reemplazar los hashes de archivo en identidades por
   versiones de política explícitas. Corregir el fit con final protegido.

Batch 6 sigue pausado y no lo retomaría hasta tener cobertura estable.

---

## 2. Hallazgos priorizados

Clasificación: **RC** = regresión confirmada con los mismos inputs; **DP** =
defecto previo (existía antes de los batches); **PI** = política conservadora
intencional; **IP** = inconsistencia del proveedor; **INC** = incertidumbre que no
se puede resolver con lo guardado.

### H1. El segundo pase convierte diferencias de recorte en "lecturas alternativas" que bloquean el cue entero (DP + RC)

- **Origen del dato.** `aidub/second_pass.py:211–235`. La ventana del segundo
  pase se recorta a `max(prev_end, start-pad)` / `min(next_start, end+pad)`. Las
  palabras se filtran a `start-0.15 … end+0.15`. Cualquier diferencia exacta de
  tokens (`es_tokens_exact`) crea `asr_alternatives`. Es el mismo modelo
  (turbo) con otra decodificación; `docs/quality.md` lo reconoce: "not an
  independent model".
- **Efecto.** `fidelity.readings_differ` (`aidub/fidelity.py:34`) y la rama de
  `eligibility` (`aidub/fidelity.py:124–133`) retienen el cue completo si la
  diferencia es `localized` o `material`.
- **Medido en el job.** 124 cues tienen alternativa y solo 17 se colocaron. Las
  alternativas son más cortas que la primaria en 72 casos, más largas en 27 e
  iguales en 25. Categorías de las 107 omisiones con alternativa: acento o
  puntuación 4; solo bordes 38; una palabra interior 23; 2–3 palabras 34; más
  de 3 palabras 8.
- **Clasificación.** Generar alternativas por recorte es **DP**. Convertirlas en
  retención total es **RC** de `79cdcfd`: el diagnóstico encontró 83 cues
  (351,9 s) que pasaron de elegibles a retenidos sobre los mismos inputs.
  `d4d85ee`/`8eb4e4c` lo suavizaron solo para `equivalent`/`minor`.
- **Riesgo de corregirlo.** Los recortes de borde pueden esconder una negación
  inicial (234 "No sé" frente a "sé"). Por eso hace falta la guardia crítica,
  no aceptar "borde" como inocuo.

### H2. El validador obliga a elegir la lectura del recorte contextual y rechaza la primaria completa (RC)

- `aidub/source_resolution.py:254–269`. `reading` debe coincidir con una
  lectura completa suministrada. Si las lecturas difieren de forma `localized`,
  además debe ser `equivalent/minor` respecto del texto *inside* del recorte
  contextual. En la práctica esto favorece la lectura truncada y rechaza la
  primaria que conserva el conector o la apertura (cues 2, 4, 155 en el
  diagnóstico). `8eb4e4c` agregó una excepción, pero solo para contexto
  independiente que difiere en un conector o equivalencia ya calificada.
- El modelo no recibe audio; recibe listas de palabras con probabilidades. La
  "adjudicación acústica" es razonamiento textual sobre dos transcripciones del
  mismo ASR. Repetir la misma evidencia en la ronda 2 y en la recuperación
  contractual no agrega información.
- **Evidencia nueva.** En 53 de los 61 cues localizados que la revisión normal
  aceptó, todas las respuestas guardadas del revisor de fuente dicen
  `supported`/`minor`. El rechazo es solo del validador.

### H3. El feedback del validador empuja al modelo a declarar incertidumbre (RC/IP)

- `aidub/review.py:100–102`: "Either accept unchanged English only with an
  appropriate source-uncertainty status, or provide a justified actual English
  revision". La recuperación contractual de `aidub/batches.py:206` dice
  "Validation feedback is binding".
- Para el error "divergent … need contextual acoustic support" solo hay dos
  salidas: elegir el recorte o declarar `material`. En 8 cues el revisor dijo
  `supported` en sus primeras respuestas y pasó a `material` después del
  feedback (176, 202, 251, 280, 296, 597, 622, 667). Esa abstención no aporta
  evidencia nueva; es una respuesta al contrato.

### H4. Campos de contrato administrativos causan fallos sin relación con el sentido (DP de diseño)

- Al modelo se le pide copiar `evidence_id`, un hash de 64 caracteres
  (`aidub/source_resolution.py:232`). También se le pide citar exactamente una
  lectura completa (`:255`), y `revise` con texto idéntico se rechaza
  (`aidub/review.py:158`).
- Flags en las 88 omisiones "C" del diagnóstico: `evidence_id` 9, cita
  exacta 19, revise sin cambios 6, entre otros que se solapan.
- El esquema JSON de `scripts/provider_codex.py:76–85` tampoco restringe
  `evidence_id` ni los IDs a enumeraciones. La vinculación debería hacerla el
  código y no el modelo.

### H5. Los presupuestos permiten terminar con inglés válido sin confirmar (PI con defecto estructural)

- Revisión normal: `max_rounds` acotado en `aidub/review.py:239`. Resolución de
  fuente: dos rondas en `aidub/source_resolution.py:431`. Una revisión en la
  última ronda queda `revised_unconfirmed` para siempre.
- Afecta a 32, 62, 644 y 812, y antes a 595/636. 644 cambió "This person's" por
  "This person is": un cambio estilístico consumió la última ronda. La
  calificación fresca confirmó 32/595/636 sin cambios y 62 con una revisión
  real. 812 volvió a cambiar.
- Exigir confirmación exacta del texto final es correcto. El defecto es que la
  última ronda admita `revise`.

### H6. La unidad de retención es demasiado grande (DP)

- 23 cues duran más de 10 s; el máximo es 28,9 s. `join_short_pauses`
  (`aidub/context.py:205`) une cues hasta 10 s, y los segmentos de Whisper
  pueden superar eso. Una duda localizada silencia pasajes enteros: 155 dura
  26,2 s, 31 dura 19,5 s y 202 dura 20,8 s.
- El mecanismo para recuperar cláusulas (`supported_spans`,
  `aidub/source_resolution.py:285–355`) exige rangos de palabras del LLM,
  límites de pausa o puntuación, una revisión y una confirmación idéntica. **No
  hubo ninguna aceptación en vivo** en ninguna evaluación. Además obliga a
  mantener linaje y padres en el manifiesto y una excepción de contexto en
  `aidub/quality_flow.py:47–53`.

### H7. El replay ignoraba recuperaciones válidas guardadas (RC de continuidad; corregido en código, no migrado)

Cubierto por el diagnóstico: 83/123/523 eran aprobaciones ignoradas y
61/655/656/671 tenían marcadores contradictorios. `f904a3e` lo corrige con
`aidub/saved_decisions.py`. Conservar.

Nota de diseño: `replay_saved_batch` revalida filas viejas con el validador
*actual* (`aidub/saved_decisions.py:124`). Así 392/428 pasaron a elegibles al
cambiar la política. Es útil, pero vuelve la reproducibilidad dependiente del
código. Hay que registrar la versión de política en cada recibo (ya se registra
`validation_policy`) y exigir la compuerta de corpus antes de aceptar un cambio.

### H8. El fit planifica sobre el núcleo recortado y rechaza después el final protegido (DP)

- `_attempt_from_audio` (`aidub/pipeline.py:477–541`) calcula el tempo con la
  duración recortada. `_present_v3` (`aidub/pipeline.py:1182–1243`) agrega el
  margen y la cola protegidos y rechaza con `protected_edge_outside_window_after_tempo`
  sin volver a planificar.
- 402: exceso de 5,02 ms; un tempo de ≈1,0021–1,0104 entraría bajo 1,10.
  127: 5,2 ms. 457 no es marginal (≈1,24) y debe seguir retenido.
- Las funciones son idénticas a `418f205` según el diagnóstico. No es una
  regresión.

### H9. Límites de alineación aproximados que parecen problemas de TTS (DP/INC)

- Palabras de duración cero (671: 5 de 7 entradas). El diagnóstico de límites
  solo bloquea por debajo de 0,12 s (`aidub/fidelity.py:203`).
  `timeline.json` declara "approximate, not forced alignment".
- Un fallo de fit dispara la reparación compacta, que puede recortar sentido,
  cuando la causa es la ventana. Falta una detección de "alineación colapsada"
  que derive a "límite dudoso" en vez de "voz demasiado larga".

### H10. Las identidades por hash de archivo invalidan etapas lejanas ante cualquier edición (DP de diseño, agravado)

- `events.identity` incluye `sha256(fidelity.py)` (`aidub/events.py:30–31`) y
  entra en la huella de **transcribe** (`aidub/pipeline.py:247`). Cada edición
  de la política de elegibilidad vuelve a correr la etapa de transcripción y
  segmentación. Las palabras ASR quedan cacheadas, pero el riesgo de cambiar
  IDs o spans es real.
- `verification_identity` y `hearing_identity` hashean `quality.py`, `audio.py`,
  `asr_worker.py` y `textnorm.py` (`aidub/verification.py:34–85`). Editar
  `audio.py` invalida hearings y waveform facts de ~3.600 tomas.
- La procedencia del proveedor incluye los hashes de `review.py`, del adaptador,
  del binario CLI y de `codex_provider.py` (`aidub/codex_provider.py:61–72`).
- Es correcto, pero caro e impredecible. Esto explica parte del peso de las
  "migraciones explícitas".

### H11. La selección por consistencia de voz depende del orden (DP, afecta a la migración)

`running_profile(chosen_profiles)` (`aidub/pipeline.py:906`) hace que cada
elección dependa de las anteriores. Agregar cues puede reordenar tomas
posteriores ya escuchadas (precedente: el cue 7 en el preview del batch 5). El
schedule de 714 de la evaluación reutilizó los 706 vecinos como fixture. Una
reconstrucción real puede elegir tomas distintas para parte de ellos.

### H12. Operación desatendida: un fallo detuvo la noche y nadie la reanudó (DP operacional)

- `runs/overnight/.../events.jsonl`: `worker_exited exit 1 provider_handoff` a
  las 05:23, reinicio manual a las 14:09. Después hubo tres salidas más por
  handoff y un `failed`.
- El aislamiento por cue arregla la causa de contenido. Los fallos transitorios
  de infraestructura (timeouts, cortes) siguen terminando el supervisor sin
  reintento diferido.
- El binario del proveedor vive en el caché de `npx`
  (`~/.npm/_npx/.../codex`): puede desaparecer y cambia la identidad al
  actualizarse.

### H13. Los tests no protegen la cobertura (DP de proceso)

- `79cdcfd` pasó todos los tests mientras retenía 83 cues adicionales. Ningún
  test reproduce la elegibilidad sobre el corpus guardado completo.
- Los tests están organizados por batch (`test_batch2/4/5`) y no por
  comportamiento. Las partes parciales se prueban solo con rangos sintéticos
  perfectos.
- El fallo preexistente `test_legacy_transcript_ids_survive_quality_only_migration`
  es casi seguro un test desactualizado. Calcula la huella legacy con toda
  `cfg['segmentation']`, que incluye `untranscribed_energy_policy`, mientras que
  el código la excluye (`aidub/pipeline.py:237`, desde `d1cdf30`). Basta un
  cambio de una línea en el test.

### H14. El harness de estudio parchea el producto con `sitecustomize` (riesgo de validez)

`jobs/.coverage-bounded-20261017/hooks/sitecustomize.py` reemplaza
`stage_inspect/extract/transcribe/schedule`, `invoke_provider` y
`target_segments`. Es válido como estudio acotado, pero "auto normal" queda
parcialmente parcheado. Conviene que el producto exponga flags explícitos
(`--only-ids`, `--stop-before`, `--frozen-from`) para que los estudios no
dependan de monkeypatching.

---

## 3. Trazado de punta a punta

| Etapa | ¿Se pierde contenido soportado? | ¿Puede aceptarse un error de sentido? | Clasificación |
|---|---|---|---|
| Ingesta/mapping | No se observó. Los roles se verificaron por grabación (mic=2, game=1, mixed=0 en oct16). | Un mapping incorrecto doblaría el audio equivocado; hoy se mitiga verificando manualmente. | PI |
| Segmentación/duplicados | Cues largos hacen que una duda pequeña silencie mucho (H6). La deduplicación conserva palabras únicas (`7c3e008`). | Un duplicado mal resuelto podría repetir o perder una frase; está cubierto por la segunda escucha. | DP |
| Evidencia ASR | Las alternativas por recorte disparan retención (H1). Palabras de duración cero (H9). | Una lectura primaria errónea aceptada por el revisor: posible en diferencias léxicas sin guardia crítica. | DP/INC |
| Eventos/gaps | 92 regiones ininteligibles y 20 eventos sin resolver bloquean `complete`, aunque nunca podrían doblarse sin texto. | No se inventa habla (bien). | PI |
| Contexto | Sin pérdida observada. | Un glosario erróneo puede sesgar; el riesgo es bajo. | — |
| Traducción/revisión | 4 cues retenidos por fallo de revisión antes del replay. Última ronda sin confirmar (H5). | La revisión normal es la principal defensa de sentido. Sin escucha humana no hay medición. | PI/IP |
| Fuente/fidelidad/elegibilidad | **Mayor pérdida** (H1–H4): 88 omisiones "C" más 13 materiales más 4 por confirmación. | Las guardias de polaridad y número funcionan (234/676 retenidos). Actor/acción dependen del revisor (644). | RC + PI |
| Cachés/identidades | Hoy no pierden contenido, pero encarecen las correcciones (H10). | — | DP |
| Workers/locks/recovery | Batch 1 es correcto; sin omisiones por infraestructura en el resultado final. | — | Conservar |
| Síntesis/selección | 4 de 115 tuvieron intentos de síntesis; Qwen no es el cuello de botella de cobertura. | La verificación ASR filtra truncados; la naturalidad no está medida. | Conservar |
| Límites/finales | 402/127 por milisegundos (H8); 457 es real. | No se corta ningún final (bien). | DP |
| Mezcla/export/validación | No se pierde nada en la mezcla (706 = 706). Game bed y picture pasan. | — | Conservar |
| Reportes | Las etiquetas de razón no son causas raíz; `source_readings_pending_resolution` mezcla fallos de contrato. | Riesgo de diagnóstico, no de sentido. | DP |

---

## 4. Localización de la incertidumbre (preguntas del punto 3)

- **¿La unidad es la adecuada?** No. La incertidumbre se detecta por rango de
  palabras (`compare_readings` ya produce `changes`), pero se aplica al cue
  completo. La unidad natural es el grupo de respiración (2–8 s, cortado en
  pausas de 0,25–0,35 s o en puntuación), definido **antes** de traducir y
  agrupado por `utterance_id` como contexto.
- **¿Se puede conservar una cláusula sin aprobar el fragmento incierto?** Con
  la arquitectura actual solo vía `supported_spans`, que nunca funcionó en
  vivo. Con segmentación previa, sí: la unidad dudosa se omite y las vecinas se
  doblan con contexto. Omitir palabras dentro de una frase doblada suena peor
  que omitir el grupo completo, así que no lo recomiendo.
- **¿Los presupuestos hacen estructuralmente posible terminar sin confirmar?**
  Sí (H5). Se corrige con una ronda final de solo confirmación (`ok` o
  `disputed`, sin `revise`).
- **¿Se repite evidencia sin aportar información?** Sí. Las mismas hearings
  reaparecen en la ronda 2 y en la recuperación contractual, todas del mismo
  modelo turbo. La retrotraducción no informa sobre la fuente. La única
  evidencia nueva real sería otro modelo acústico, por ejemplo large-v3, que no
  está instalado y requiere tu autorización, o un modelo con entrada de audio.
- **¿Se confunden límites ASR malos con voz demasiado larga?** Sí, en parte
  (671, y el camino de reparación compacta ante fallos de fit). Hace falta
  detectar la alineación colapsada antes de pedir texto más corto.

---

## 5. Auditoría de simplificación

### 5.1 Inventario de duplicaciones y capas solapadas

| Área | Duplicación / solape | Propuesta |
|---|---|---|
| Elegibilidad | `fidelity.eligibility`, `source_uncertainty_issues` (rama legacy y nueva), `voicing_uncertainty`, `_cache_misses`, `targeted_review` (contadores) | Un solo `eligibility(seg, policy)` que devuelve un estado de una tabla corta; borrar la rama legacy cuando no queden snapshots viejos activos. |
| Polaridad y tokens | `fidelity.tokens/polarity_tokens/reading_tokens`, `source_disagreement._tokens`, `second_pass.es_tokens(_exact)`, `textnorm` | Un tokenizador español con normalización explícita y un conjunto crítico (negadores, números). |
| Validación de revisión | `review.validate_review_response`, `batches._envelope_error`, `saved_decisions.envelope_error`, `providers.response_errors`, `assessment_errors` | Un validador de sobre y un validador de fila; eliminar `assessment_errors` de la política v3. |
| Replay de respuestas | `providers` (state machine), `batches._saved_invalid_response`, `saved_decisions.replay_saved_batch`, `source_resolution.saved_source_response`, `restore_translation_if_response_matches` | Conservar `saved_decisions` como único reductor; quitar `saved_source_response` junto con el bucle de fuente. |
| Confirmación de inglés | `run_review` (rondas), `source_resolution` (2 rondas), `review_pending_repairs`, `reconfirm_resolution`, `targeted_review` | Una revisión con ronda final de confirmación; `review_pending_repairs` la reutiliza. |
| Estados de revisión | `accepted_draft`, `revised_confirmed`, `revised_unconfirmed`, `disputed`, `accepted_source_resolution`, `accepted_targeted_review`, `accepted_supported_span`, `withheld_review_failure`, `withheld_translation_failure` | Cinco estados: `accepted`, `pending_confirmation`, `disputed`, `withheld_contract`, `withheld_infra` (los dos últimos no son omisiones ordinarias). Los históricos se mapean al leer. |
| Presentación | `_present_v3`, `_present_v2`, ruta v1 en `_apply_presentation` | Mantener v2 y v1 solo mientras haya snapshots que los usen. |
| Identidades | Hashes de archivo en ≥8 lugares (H10) | Constantes de versión por política más un test que falla si cambia el código hasheado sin subir la versión. |

### 5.2 Productivo frente a harness

- **Productivo:** `aidub/*`, `bin/aidub`, `scripts/provider_codex.py`,
  `scripts/overnight.py`.
- **Herramienta de estudio que se conserva:** `scripts/evaluate_saved_coverage.py`
  (base del futuro `aidub replay-eligibility`).
- **Hooks ignorados** en `jobs/.*/hooks`: son evidencia de estudio. Se
  conservan, pero no deben ser el mecanismo para calificaciones futuras.
- **Evidencia que se conserva:** `jobs/*`, `jobs/.*-eval*`, `runs/diagnostics`,
  `runs/overnight`.

**Limpieza aplicada después de esta revisión (2026-10-17, sin commit).** Se
quitaron del árbol de trabajo:
- la documentación histórica: `PLAN.md`, `PROVENANCE.md`,
  `docs/optimization-plan.md`, `continuity.md`, `hardening-verification.md`,
  `host-verification.md`, `performance-progress.md`, `performance-results.md`,
  `roadmap.md` y `validation.md`;
- los reportes de corridas viejas en `runs/` (quality, unattended,
  reference-comparison, minute-original-investigation);
- los scripts de estudios pasados: `compare-jobs.py`, `continuity-evidence.py`,
  `performance-evaluate.py`, `benchmark-block-audio.py`, `run-measured.py` y
  los dos scripts de host verification, junto con sus tests;
- `aidub/targeted_review.py` y el subcomando `accept-targeted-review`;
- `scripts/provider_cursor_agent.py`;
- el fallback de proveedor del supervisor nocturno.

Todo se recupera con `git checkout 8eb4e4c -- <ruta>`. El handoff no
trackeado y la cabecera no commiteada del plan de optimización están en
`/home/siamarino/ai-dubbing-archive/asr-batch1-cleanup-20261017/`. Las
referencias a esos archivos dentro de este informe y de `runs/diagnostics` son
históricas.

### 5.3 Tabla de decisiones

| Elemento | Decisión | Justificación | Costo / riesgo |
|---|---|---|---|
| Batch 1 (lifecycle ASR, recuperación persistida, completitud) — `17d2335` | **Conservar** | Sin omisiones por infraestructura; evita aprobar hearings incompletas. | — |
| Batch 2 (revisión antes de finalizar, sin retrotraducción final) — `fb66b11` | **Conservar** | Ahorra finalizaciones; protege el texto exacto. | — |
| Batch 3 (Luna/medium/ChatGPT, procedencia, sin fallback) | **Conservar**; **modificar**: ruta estable del binario y procedencia por versión de contrato en vez de hash de `review.py` | Requisito explícito. | Bajo |
| Batch 4 (comparación española opcional) — `bb86e72` | **Conservar** | Ahorra ~53 GB y tiempo de finalización. | — |
| Aislamiento por cue y feedback — `186e5b2`, `81d96f7`, `7eb387a`, `7053d1b`, `2384395` | **Conservar** | Hace posible el parcial útil. | — |
| Replay determinista — `f904a3e` | **Conservar** | Corrige decisiones perdidas. | — |
| Clasificador de diferencias — `d4d85ee` | **Modificar**: usarlo para reportar y marcar, no para retener `localized` si la revisión aceptó; pasar a comparación alineada en tiempo | Base útil. | Bajo |
| Guardia numérica — `8eb4e4c` (`acoustic_numbers_differ`) | **Conservar** como guardia crítica determinista | Protege 676. | — |
| Excepción de contexto independiente — `8eb4e4c` | **Eliminar** al adoptar v3 (queda subsumida) | Era un parche sobre la regla de igualdad. | Bajo |
| Retención por `readings_differ` y regla de lectura contextual — `79cdcfd` | **Revertir el comportamiento** (no `git revert` del commit entero): sacar la rama `readings_differ→material` y la regla `divergent … contextual acoustic support` | RC: 83 cues sobre los mismos inputs; 53 cues aceptados por todos los revisores. | Riesgo de sentido en diferencias léxicas, acotado por la guardia crítica y el gold set |
| Guardia de polaridad (`material_conflict`, chequeo de negadores) — `0af787e`/`344bc27` | **Conservar** | Protege 234/685. | — |
| Bucle LLM de "adjudicación acústica" (`source_resolution` para cues léxicos) | **Retirar del camino por defecto** en jobs nuevos; mantener el código en modo solo lectura para replay de jobs viejos hasta migrarlos | El modelo no oye; 49 % de respuestas inválidas; la ganancia neta útil ronda 8 cues frente a ≥83 retenciones. | Medio (afecta snapshots) |
| Revisión LLM de gaps/eventos | **Eliminar**; usar disposición determinista (casi silencio sin palabras → no habla; el resto se reporta) | Un modelo de texto no identifica risas ni ruido. | Bajo |
| `supported_spans`, `_apply_parts`, padres y contexto especial | **Eliminar** (lo reemplaza la segmentación previa) | Nunca se aceptó en vivo; alta complejidad. | Bajo |
| `targeted_review.py` y `accept-targeted-review` | **Eliminar** tras archivar | Superado por auto; exige `kind == "command"` y el modelo fijo. | Bajo |
| `scripts/provider_cursor_agent.py` y el default de `providers.py:48` | **Eliminar** | El batch 3 prohíbe depender de Cursor. | Bajo |
| Ronda final de revisión que admite `revise` | **Modificar** a solo confirmación | H5. | Bajo |
| Fit con final protegido | **Modificar** (H8) | 402/127. | Bajo; requiere verificar la toma procesada |
| Selección dependiente del orden | **Modificar**: selección "pegajosa" para cues sin cambios | Evita reordenar escuchas aprobadas. | Bajo |
| Hashes de archivo en identidades | **Modificar** a versiones explícitas | H10. | Medio (migración de identidades); hacerlo con tabla de equivalencias |
| Hash completo de la fuente en cada `inspect` | **Posponer** la optimización (atajo por `stat` con hash final en validación) | 26–78 s por arranque; la integridad se mantiene. | Bajo |
| Reducción adaptativa de candidatos | **Posponer** | La síntesis domina el runtime (~2,2 h) pero falta evidencia de escucha. | — |
| Batch 6 (concurrencia) | **Posponer** | Los proveedores sumaron ~36 min de 2,79 h activas; el beneficio es secundario frente a cobertura e idle. | — |
| Tests `test_batchN` | **Modificar** gradualmente: renombrar por comportamiento y agregar la compuerta de corpus | H13. | Bajo |
| `test_legacy_transcript_ids_survive_quality_only_migration` | **Corregir el test** (excluir `untranscribed_energy_policy` de la huella esperada) | Desactualizado desde `d1cdf30`. | Muy bajo |

---

## 6. Medición propuesta

**Cobertura.** Separar y nunca sumar intervalos solapados:

1. Cues: colocados / total.
2. Ventanas de cue colocadas / total (aproximación de ventana, no de habla).
3. Unión recortada de intervalos de palabras primarias de cues colocados /
   unión de todos los cues, más las regiones ininteligibles deduplicadas. Es un
   proxy de habla y no una medida exacta.
4. Embudo: elegibles → sintetizados → colocados → exportados y validados, con
   la causa primaria disjunta de cada omisión (5–7 categorías, no etiquetas de
   código).

**Fidelidad.**

- Gold set de ≈60 cues de este job, estratificado: controles 234/676/685/125/171/644;
  diferencias de borde y de una palabra; pasajes largos; 20 al azar. Lo
  etiquetás vos una vez, escuchando el micrófono: lectura correcta, si la
  diferencia ASR importa, y si el inglés es fiel.
- Métrica: errores materiales (polaridad, número, actor, acción, referente),
  omisiones de contenido soportado y adiciones, cada 100 cues colocados; y
  falsos bloqueos cada 100 cues retenidos.
- Se reutiliza para cada versión de política sin pagar proveedores.

**Naturalidad y parecido de voz.**

- El protocolo existente de 12 extractos ciegos A/B aleatorizados, con notas de
  defectos fechadas.
- Escala de 1 a 5 para calma, naturalidad y parecido. Es una ayuda y no prueba
  identidad.
- Proxies técnicos: distribución de tempo (% > 1,05), finales verificados,
  pausas conservadas.
- Sin embedding de hablante instalado, no hay métrica automática de identidad.

**Runtime y operación.**

- Por etapa: wall time, intentos de proveedor e inválidos (%), hits de caché,
  tomas por cue colocado, inferencia Qwen, hearings, mezcla y validación.
- **Intervenciones manuales**, con objetivo 0.
- **Tiempo ocioso entre reinicios del supervisor**.
- Tiempo hasta el primer parcial exportable.
- Para comparar de forma justa: misma grabación, mismos inputs congelados,
  mismo estado de caché (frío contra frío o tibio contra tibio). Nunca comparar
  totales de grabaciones distintas.

**Escucha humana.** No se realizó. Es necesaria para aprobar naturalidad y voz
y para etiquetar el gold set. La revisión técnica no depende de ella para
recomendar el rumbo.

---

## 7. Evidencia que falta y la prueba mínima que la obtendría

| Falta | Prueba mínima |
|---|---|
| Verdad de fuente para diferencias localizadas | Gold set de 60 cues etiquetado por vos (≈60–90 min de escucha del mic). |
| Seguridad de la política v3 sobre los 53 cues | Escucha estratificada de 15 de los 53 (sí/no material) antes de migrar. |
| Si un modelo acústico distinto resuelve conflictos críticos | Si autorizás large-v3: correrlo solo sobre los ~20 cues críticos guardados y comparar contra el gold set. |
| Si la segmentación en grupos de respiración mantiene la naturalidad | Clip de 150 s y muestra de 15–20 min nueva, A/B ciego contra la segmentación actual. |
| Comportamiento desatendido de punta a punta | Grabación nueva de 15–20 min con `auto` sin intervención, más una interrupción y reanudación controlada. |
| Efecto de la selección pegajosa | Reconstruir el schedule del job oct16 con caché y contar cues reordenados (sin síntesis nueva). |

---

## 8. Cifras derivadas en esta revisión (reproducibles por lectura pura)

- `manifest.json`: 821 cues; 124 con `asr_alternatives`; estados de revisión:
  accepted_draft 753, accepted_source_resolution 22, disputed 18,
  revised_confirmed 17, revised_unconfirmed 7, withheld_review_failure 4.
- Omisiones con alternativa: 107/115. Sin alternativa: 61, 127, 402, 457, 546,
  644, 655, 812.
- Proveedor (todos los `state.json` bajo `handoff/`): 202 intentos, 99
  `invalid_response`. Intervalos: revisión de fuente 1.225 s (103 intentos),
  revisión normal 535 s (50), traducción 322 s (42), resto < 60 s.
- Supervisor: parada 05:23→14:09 UTC; `schedule` del primer pase ≈7.965 s con
  ~3.600 tomas (incluye síntesis y verificación).
- Pool de 53 cues (`remaining_causes.json`, categoría
  `localized_source_review_contract_exhausted`, intersectada con: primera
  revisión `accepted_draft`/`revised_confirmed`, sin diferencias de
  negación o número, inglés sin cambios y sin ninguna respuesta de fuente
  `material`; se excluyeron además 142/199 por abstención material guardada):
  59, 97, 110, 114, 119, 148, 149, 155, 158, 162, 193, 207, 225, 230, 274, 285,
  297, 298, 299, 343, 351, 375, 377, 429, 431, 444, 459, 486, 495, 526, 550,
  556, 574, 629, 637, 645, 658, 677, 681, 698, 702, 709, 718, 727, 740, 758,
  760, 762, 776, 778, 790, 795, 807. Ventanas: 172,935 s. Ninguno tiene
  diagnóstico de límite bloqueante. **Es un pool candidato, no una recuperación
  certificada.**

---

## 9. Funcionamiento actual del pipeline (estado en `8eb4e4c`)

> Versión explicada en lenguaje simple: [pipeline-explicado.md](pipeline-explicado.md).
> Lo que sigue es la referencia técnica.

Descripción resumida pero completa del comportamiento real del código, con la
configuración del job oct16 (preset `performance`, `source_events` y
`source_resolution` activos). Los números entre paréntesis son los valores de
ese snapshot. Documentación previa, fragmentada:

| Documento | Qué cubre | Estado |
|---|---|---|
| `README.md` → "What runs" | Tabla de etapas | Desactualizada: no menciona segundo pase, revisión, resolución de fuente, best-of-N ni presentación v3 |
| `docs/architecture.md` | Persistencia, handoffs, replay, aislamiento por cue | Correcta pero narrativa; se actualizó la lista de estados y se enlaza esta sección |
| `docs/unattended.md` | Locks, identidades de batch, intentos de proveedor | Vigente |
| `docs/quality.md` | Qué agrega el preset quality | Vigente; no cubre batch 5 |
| `docs/configuration.md` | Claves de configuración, incluida la resolución de fuente | Vigente |
| `docs/overnight.md` | Supervisor nocturno | Vigente; ver 9.6 sobre su límite real |

### 9.1 Vista general

```
bin/aidub auto  ──►  unattended.run_unattended  (toma JobLock del job; ≤ max_handoff_rounds=12 vueltas)
   │
   └─► pipeline.run_job (bajo el mismo lock)
         inspect → extract → transcribe ──► ¿falta inglés o cambió el transcript?  ─► awaiting_translation (exit 2)
                                         ──► ¿reparación compacta sin revisar?      ─► awaiting_repair_review (exit 2)
                                         ──► ¿episodios de fuente pendientes?       ─► awaiting_source_review (exit 2)
         schedule (síntesis + verificación + fit + presentación)
                                         ──► ¿cues que necesitan texto más corto?   ─► awaiting_repair (exit 2)
         mix/export → validate → risk report  ─► complete (0) | partial (3) | failed (1)

   run_unattended atiende cada exit 2 y vuelve a llamar a run_job:
     awaiting_translation   → quality_flow.translate_with_review → accept_translation
     awaiting_repair_review → quality_flow.review_pending_repairs
     awaiting_source_review → source_resolution.resolve_sources
     awaiting_repair        → provider "repair" (batches) → accept_repair
```

**Estados del job:** `pending`, `running`, `awaiting_translation`,
`awaiting_repair_review`, `awaiting_source_review`, `awaiting_repair`, `failed`,
`partial`, `complete`.

**Códigos de salida:** 0 complete, 3 partial, 1 failed o error de proveedor,
2 handoff (solo en el modo manual `run`/`resume`, que nunca llama
proveedores), 85 (parada deliberada de los estudios con hooks; no es un
estado del producto).

**Reutilización de etapas.** Cada etapa guarda `status + fingerprint + outputs`
en `manifest.json` (escritura atómica) y se salta si la huella y los archivos
coinciden (`_fp_ok`). Si una etapa aguas arriba cambia, las de aguas abajo
(`schedule`, `mix`, `validate`) pasan a `pending`.

### 9.2 Etapas

| Etapa | Qué hace | Reintentos / recuperación | Checkpoint e identidad |
|---|---|---|---|
| **inspect** | ffprobe; ordinales de audio; duración por PTS si falta; compatibilidad de contenedor; presupuesto de disco; **hash SHA-256 completo de la fuente en cada arranque** (26–78 s en oct16). | Ninguno: falla si la fuente cambió. | `inspect/probe.json` |
| **extract** | ffmpeg extrae mic/game/mixed por `0:a:N` sin seek; alineación por headers. | Ninguno. | Huella independiente por pista; `extract/alignment.json` (incluye `mic_sha256`) |
| **transcribe** | 1) Whisper turbo en ventanas de 600 s con 2 s de solapamiento, con palabras con timestamp; checkpoint por ventana. 2) Segmentación por mapa de energía en disco (RMS 0,005 / 10 ms). 3) **Segundo pase** (mismo turbo, beam 5, otra ventana): duplicados entre cues vecinos (confirmar repetición, borrar o recortar), cues con palabras inciertas (crea `asr_alternatives` ante cualquier diferencia exacta de tokens) y gaps con energía sin texto (se recupera un cue solo con palabras confiables confirmadas en una ventana más amplia; si no, `unintelligible`, `no_speech_heard` o `non_speech_energy`). 4) Unión de cues separados ≤ 0,35 s (máx. 10 s, 3 partes, sin unir reacciones). 5) Eventos vocales (vacilaciones; `material_source_conflict` si cambia la polaridad entre lecturas). 6) Pausas de la fuente. | Las hearings del segundo pase se cachean por ventana. El worker se lanza una vez por etapa. | La huella incluye pesos, segmentación, segundo pase, unión y **hashes de `events.py` y `fidelity.py`**. Si los IDs/spans/español no cambian, se conserva la traducción aceptada. |
| **Handoff de traducción** | 1) **Contexto**: 1 llamada por parte (≤ 60.000 caracteres) → resumen, registro, glosario (cada término debe existir en el transcript), notas de estilo. 2) **Traducción** en batches (≤ 40 cues; ≤ 60.000 caracteres) con contexto global, 3 vecinos por lado, `utterance_id`, sílabas objetivo y máximas, alternativas ASR y eventos. 3) **Revisión bilingüe**: ronda 1 con todos; ronda 2 solo revisados o disputados (`max_rounds=2`). La retrotraducción se pide solo para disputados y solo si hay otra ronda que la use. 4) `accept_translation`. | Ver 9.3 (intentos por identidad, recuperación por subconjunto, replay). | `handoff/context`, `handoff/batches/<rol>/<identidad>/batch_NNNN/`, `handoff/translation_audit.json` |
| **Handoff de revisión de reparaciones** | Si una reparación compacta cambió el inglés y ese texto exacto no tiene revisión, se revisa con `run_review` (mismas rondas) antes de sintetizar. Si queda `accepted`, se re-vincula la resolución de fuente vigente. | Igual que la revisión. Las revisiones finales sin confirmar quedan retenidas. | `handoff/repair_reviews/<identidad>/` |
| **Handoff de resolución de fuente** | Objetivos: cues con conflicto de polaridad, con lecturas distintas o con revisión `disputed`/`revised_unconfirmed` que hoy no son elegibles, más gaps `unintelligible` y eventos sin resolver. Por objetivo se crea un **episodio** (clave: mic, span, español, alternativas, ajustes y pesos de la escucha) con: a) evidencia acústica, que reutiliza la escucha guardada del segundo pase o hace **1 escucha contextual nueva** (±1,25 s; el presupuesto se reserva antes de llamar); b) **≤ 2 rondas semánticas** con el rol `review`, que deben devolver `source_assessment {confidence, reading, evidence_id, reason, parts}`. El validador (`assessment_errors`) exige: `evidence_id` exacto; lectura igual a una lectura completa suministrada; soporte léxico con p media ≥ 0,6; si la diferencia es `localized`, coincidencia con el recorte contextual; sin números en competencia; polaridad con un negador confiable en la escucha contextual; y para `supported_spans`, rangos con límites de cláusula, una revisión y luego una confirmación idéntica. | Por batch: intentos de proveedor y luego recuperación de subconjunto; las filas inválidas al final pasan a "fallo de contrato" y el episodio queda `finished` y retenido. Cada ronda cierra sus decisiones primero en el manifiesto y después en `state.json` (recuperable ante un crash entre ambas escrituras). | `handoff/source_resolution/{state.json,acoustic/,requests/,responses/}`; política `aidub.source_resolution.v1` |
| **schedule** | Recorre los cues por tiempo. 1) `eligibility` (ver 9.4); si retiene, se registra la omisión sin sintetizar. 2) **Best-of-N**: semillas `primary + 1000·i` hasta 4 tomas válidas, con ≤ 4 extra que reemplazan inválidas y búsqueda de una colocable. 3) Por toma: síntesis Qwen ICL (caché por texto/semilla/referencia/ajustes); verificación ASR (texto `sequence-v1`, truncado, repeticiones, pausas > 1 s, velocidad, proxy de voz por pitch/brillo); **segunda verificación** forzada en inglés si la diferencia es solo "soft"; fit (recorte RMS 0,005; tempo hasta 1,10 con ≤ 2 correcciones; nunca pisa el cue siguiente ni el ocupado anterior); presentación v3 (márgenes y cola protegidos, loudness según la fuente, retraso de onset ≤ 80 ms; rechaza si el final protegido no entra o la cola no decae); y si hubo tempo > 1 o un prefijo de evento, **se vuelve a verificar la toma procesada**. 4) Ranking de válidas: pacing, acuerdo ASR, distancia a la referencia y a las tomas ya elegidas (**depende del orden**), pausas de la fuente y tempo. 5) Si ninguna cabe: adelantar ≤ 0,4 s a silencio previo (salvo reacciones o eventos fijos); si aun así no cabe y quedan revisiones (≤ 2), entra en `needs_repair`. | ASR: por hearing, CUDA → reinicio CUDA → CPU, con estado persistido; un worker no reapeado bloquea todo el job; evidencia incompleta → `VerificationUnavailable` (se detiene sin regenerar voz). | `cache/synth`, `cache/asr` (hearings), `cache/waveform`, `cache/quality`, `ledger/`, `checkpoints/`, `schedule/summary.json`. La huella incluye todos los campos de los cues, las políticas, la referencia, la configuración, `verification_identity` y hashes de `selection.py` y `vocal_verification.py`. |
| **Handoff de reparación** | Para cues en `needs_repair`, el rol `repair` propone un inglés más corto (`revise`) o `leave_unresolved`. `accept_repair` lo registra en `revisions` (≤ `max_shorter_translations=2`). Después vuelve el handoff de revisión de reparaciones. `leave_unresolved` es absorbente (caso 127). | Intentos del proveedor (no usa recuperación de subconjunto). | `handoff/repair_*.json` |
| **mix/export** | Mezcla por bloques: voz con ganancia por cue y márgenes y fades solo en la voz; el game bed no se escala. Mux con el picture copiado + 1 pista AAC en inglés + SRT de los cues colocados. Comparación española opcional (apagada). | Ninguno. | Huella v3; `mix/placed_summary.json`, `mix/gain.json`, `mix/spanish_compare.json` |
| **validate** (v7) | Decode, identidad del bitstream de video, duración y geometría, PCM `mix − (game + voz)`, clipping/headroom, ventanas y colocación, verificación generada, finales protegidos y eventos, `translation_reviewed`, `source_events_accounted`, `source_uncertainty_resolved` y protección de archivos. Genera `omissions.json/.md` vinculados al hash del export. Cualquier fallo requerido → `partial`. | Ninguno. | La huella incluye hashes de la fuente, de los artefactos (≈26 GB) y del código del validador. |
| **risk report** | Ranking de líneas y gaps de riesgo con extractos y previews de 720p. | — | `report/risk.md` |

### 9.3 Reintentos, presupuestos y realimentaciones

| Mecanismo | Dónde | Límite (oct16) | Qué se realimenta |
|---|---|---|---|
| Intentos por identidad de request de proveedor | `providers._invoke_checked_locked` | `max_attempts=2` (1..5) | Los errores del validador viajan como `validation_feedback` al intento siguiente. Una respuesta durable válida se reutiliza. Una llamada sin respuesta durable queda `outcome_uncertain`. Auth/cuota/config → `blocked` (permanente). |
| Recuperación de subconjunto por cue | `batches._invoke_isolated_batch` (traducción y revisión, incluida la fuente) | `content_recovery.max_attempts=1` (1..2), identidad propia | Solo las filas inválidas, con su feedback y la instrucción "Validation feedback is binding". Si se agota, esas filas pasan a `_aidub_withheld` y el resto sigue. Los errores de sobre o de IDs y las fallas de infraestructura siguen siendo globales. |
| Replay de decisiones guardadas | `saved_decisions.replay_saved_batch` | Sin llamadas | Revalida filas originales y de recuperación con el **validador actual**. La más reciente válida gana; los marcadores agregados no tienen autoridad. |
| Rondas de revisión bilingüe | `review.run_review` | `max_rounds=2` (1..4) | Historial de veredictos y retrotraducción (solo disputados, antes de la ronda siguiente). Una revisión en la última ronda queda sin confirmar. |
| Rondas de fuente | `source_resolution.resolve_sources` | 2 rondas semánticas y 1 escucha contextual por episodio | La misma evidencia y `previous_supported_parts`. Sin ronda extra de confirmación. |
| Reparación compacta | `linework` + `accept_repair` | ≤ 2 revisiones por cue | Ventana segura, duración recortada, tempo necesario e intentos previos. |
| Tomas de voz | `collect_line_best_of_n` | 4 válidas + 4 extra | Sin realimentación al texto, salvo `needs_repair`. |
| Correcciones de tempo | `_attempt_from_audio` | ≤ 2, acumulado ≤ 1,10 | Duración medida tras atempo. |
| Recuperación de hearing ASR | `_LineAssessor._hear` | CUDA, reinicio CUDA, CPU (persistido) | El error inicial se conserva; sin reset al reanudar. |
| Vueltas de handoff por proceso | `run_unattended` | `max_handoff_rounds=12` | — |
| Supervisor nocturno | `scripts/overnight.py` | ≤ 2 reintentos de proceso (10 s, 30 s) **solo para `recoverable_worker`** | Sondeo cada 12 min. `provider_handoff` (cualquier salida en estado `awaiting_*` o con `provider_error`) **detiene la supervisión** con `human_intervention_required`; el fallback de proveedor está prohibido para `codex_chatgpt`. |

### 9.4 Elegibilidad para sintetizar (`fidelity.eligibility`)

Reglas evaluadas en orden; la primera razón encontrada retiene el cue:

1. Resto no resuelto de una división (`source_remainder`).
2. Hay `source_resolution`, pero no es válida: el binding de mic, span,
   español, alternativas, evidencia e inglés exacto no coincide, no está
   confirmada, o su confianza no es `supported`/`minor`.
3. Conflicto de polaridad sin resolución válida.
4. Con resolución de fuente activa y lecturas distintas: clasificación
   `material` → retiene; `localized` → retiene; `minor`/`equivalent` → exige
   soporte léxico (p media ≥ 0,6), si no `unverified` (retiene).
5. Revisión: `withheld_*`; reparación compacta sin revisar; `checked_text` ≠
   inglés actual; `revised_unconfirmed`; `disputed`.
6. Límite bloqueante (span no positivo, solapamiento, multipalabra < 0,12 s).
7. `leave_unresolved`.

La misma función alimenta schedule, `_cache_misses`, la selección de
objetivos de fuente, la validación y los conteos de `targeted_review`.

### 9.5 Identidades y cachés (qué invalida qué)

- **Síntesis:** texto, semilla, bytes y transcript de la referencia, ajustes
  Qwen y revisión del modelo. El código no invalida la síntesis.
- **Hearing ASR:** bytes del WAV, dispositivo, modelo y pesos, decodificación,
  versión de Whisper, hash de `asr_worker.py`. **Waveform facts:** hash de
  `quality.py` y `audio.py`. **Evaluación:** umbrales, nombres del glosario,
  referencia, hashes de `quality.py`, `audio.py`, `textnorm.py`, código de
  pacing. El ranking y la cantidad de candidatos no invalidan hearings.
- **Proveedor:** request completo + spec + procedencia efectiva (modelo,
  razonamiento, auth, versión y hash del CLI, hashes del adaptador, de
  `codex_provider.py` y de `review.py`) + inglés actual en revisión. Un
  presupuesto agotado sigue agotado aunque cambie la identidad
  (`_saved_invalid_response`).
- **Transcribe:** incluye los hashes de `events.py` y `fidelity.py` (ver H10).
- **Schedule/validate:** incluyen las políticas de resolución y de
  desacuerdo, todos los campos de decisión de los cues y el código del
  validador.

### 9.6 Puntos de realimentación con efectos no obvios

- Feedback del validador → el revisor cambia `supported` por `material`
  (H3).
- Cambiar la política de validación → el replay reinterpreta filas guardadas
  (H7): puede liberar (392/428) o retener.
- Reparación compacta → revisión de reparaciones → puede restaurar el
  conector quitado → vuelve a no caber → `leave_unresolved` absorbente (127).
- Agregar o quitar cues → la selección por consistencia reordena tomas
  posteriores (H11).
- Cualquier salida en estado de handoff → el supervisor se detiene (H12).
