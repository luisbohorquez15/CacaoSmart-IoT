### Clima exterior (DEV-03, DEV-04 y DEV-09)

La temperatura exterior reportada por Azure Maps siguió un ciclo diario muy regular: promedio de **25,5 °C**, mínimo de **22,0 °C** al amanecer (06:00 del 6 nov.) y máximo de **31,1 °C** a las 14:00 del 9 nov. La humedad relativa se comportó en espejo (correlación **r = −0,80** con la temperatura): promedio de 77,9 %, con saturación del 100 % en las madrugadas lluviosas y un mínimo de 56 % el 11 nov. La nubosidad media fue alta (72,7 %), lo que explica un índice UV promedio de apenas 1,95; el UV sólo alcanzó el umbral de **8** en dos mediodías despejados (6 y 9–10 nov.).

El pronóstico (DEV-04) concentró la mayor probabilidad de lluvia entre la noche del 6 y la madrugada del 7 nov. (100 %, con 9,6 mm esperados en 12 h), que coincide con el aumento brusco de humedad del suelo registrado ese mismo día. Frente al dataset histórico de 2025 (DEV-09), noviembre de 2026 está **1,3 °C más cálido en promedio** (25,5 °C vs 24,2 °C) y más seco (HR 77,9 % vs 86,6 %); el máximo diario de 2026 superó al de 2025 en 2,3 °C. La evapotranspiración de referencia de 2025 fue estable (3,1–4,3 mm/día), lo que sugiere que el cultivo demanda hoy algo más de agua que en la misma época del año anterior.

### Microclima y suelo del lote (DEV-01 y DEV-02, nodos reales)

Bajo el dosel la temperatura fue 0,8 °C menor que la exterior (24,7 °C promedio; 30,5 °C máx.) y la humedad 3–4 puntos mayor (81,6 %), efecto esperado de la sombra del cacaotal. La HR superó el umbral de 88 % todas las noches, pero nunca coincidió con T > 26 °C durante 4 h seguidas, por lo que **no se activó la alerta de Moniliasis**: el riesgo fúngico existió de noche, pero con temperaturas demasiado bajas para el hongo.

La humedad del suelo arrancó en 44 %, cayó hasta el umbral de 35 % el 6 nov. (dos riegos) y subió hasta 59 % con las lluvias del 7 y 8 nov.; después descendió lentamente por evapotranspiración (pendiente de ~5 puntos/día en días soleados). A partir del 9 nov. la curva muestra el patrón de "dientes de sierra" típico del **Lazo 2**: cada vez que tocó 35 %, el motor de reglas consultó el pronóstico, encontró probabilidad de lluvia < 30 % y ordenó **13 riegos automáticos** de 15 min (relé de DEV-02 + bomba de DEV-06), cada uno con una recuperación de 5–7 puntos. La batería del nodo osciló entre 3,64 V y 4,06 V con carga solar diurna; los días nublados (7–8 nov.) muestran descarga neta, un dato útil para dimensionar el panel.

### Polisombra y riego (DEV-05 y DEV-06, gemelos digitales)

La radiación exterior calculada alcanzó **930 W/m²** (9 nov., 11:50) y la malla la redujo a un máximo filtrado de 724 W/m². El **Lazo 1** cerró la polisombra al 80 % en 4 ocasiones (alerta "UV alto") y la reabrió al 30 % cuando el UV bajó de 5; el diagrama de dispersión UV–cierre muestra el escalón limpio de la histéresis 5→8 (r = 0,65 por hora). En la bomba, el caudal fue 0 la mayor parte del tiempo y subió a ~30 L/min sólo durante los pulsos ordenados por el Lazo 2, con presión de 27 PSI en operación y 4 PSI estática en reposo; el consumo diario máximo fue de **1 980 L** (10 nov.), coherente con el día de mayor demanda hídrica.

### Fermentación (DEV-07, gemelo digital)

El ciclo completo de 144 h quedó registrado. La masa pasó de 23 °C a ~38 °C en la fase anaeróbica (0–36 h); el **volteo programado a las 48 h** bajó 3 °C la temperatura y, al oxigenar la masa, disparó la fase acética hasta el máximo de **46,9 °C** (8 nov., 14:00), dentro de la banda óptima de 45–50 °C. El segundo volteo (96 h) produjo un segundo repunte menor y la masa se enfrió hacia la temperatura ambiente en la maduración. El pH del mucílago subió de forma sigmoidal de 3,75 a 5,21, acorde con el consumo de ácidos por las bacterias acéticas. Como la temperatura nunca superó 50 °C, no fue necesario ningún volteo de emergencia.

### Secado solar vs. curva ideal (DEV-08 y DEV-10)

El grano bajó de **55 % a 9,2 %** de humedad en 6 días, pero **por escalones**: sólo seca en las horas de sol y se estanca (o se rehumedece levemente) por la noche y en los días nublados. Frente a la curva ideal de "sol intenso" del dataset DEV-10 (suave, 6,4 % al final), el lote real estuvo hasta 20 puntos por encima los días 7–8 nov., lo que generó **16 alertas de "secado retrasado"**; la brecha se cerró en los días despejados del 9–10 nov. La temperatura interna llegó a **50,5 °C** al mediodía del 10 nov.: el **Lazo 5** encendió los extractores y abrió compuertas (4 órdenes de extractores, 16 de compuertas), pero la temperatura igual superó los 46 °C, con **8 alertas de sobrecalentamiento**. Por la noche, y ante pronóstico de lluvia, las compuertas permanecieron cerradas para evitar la rehumectación.

### Hallazgos transversales y recomendaciones

1. **El retroceso automático funcionó en los cuatro lazos**: 64 comandos y 41 alertas en 6 días, todos trazables en la bitácora, con causa (sensor/API) y efecto (actuador) visibles en las gráficas.
2. **La API meteorológica aporta valor de decisión**: la combinación suelo (sensor real) + pronóstico (Azure Maps) evitó regar antes de la lluvia del 7 nov.
3. **La marquesina es el punto débil**: los extractores no bastan en mediodías despejados (> 46 °C). Se recomienda un lazo adicional que despliegue malla de sombra sobre la marquesina cuando UV ≥ 8, o adelantar el encendido de extractores a 42 °C.
4. **El secado depende del clima**: con la nubosidad de esta semana, el perfil "nublado" del benchmark (DEV-10) es la referencia más justa; cambiarlo por retroceso (`SET_PROFILE`) reduciría las alertas espurias.
5. La correlación casi nula entre la temperatura de la masa y el clima exterior (r = 0,15) confirma que la **fermentación está gobernada por su propia dinámica microbiana**, no por el ambiente.
