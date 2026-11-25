# References

This page lists the published works, and the software documentation, code and data pages, that the EEGLayoutLab method and design draw on. Installation tools, licences and security advisories are linked where the documentation uses them and are not repeated here. Each entry gives the full citation as plain text, the DOI or other formal identifier, and a link. A work can still be found from the citation if a link stops working.

The works document external methods, related findings and design guidance. They do not validate this application's layouts or implementation.

## How to read an entry

Each entry has one or two short notes.

- **Supports** names the part of EEGLayoutLab that the work relates to, in the terms this documentation uses, and the finding that bears on it.
- **Limits** appears only where the work cautions against a choice, reports a weaker result for a restricted layout, or bounds what a method can show.

A note states a finding only when it was confirmed in the abstract or the full text. Where the work was not re-read, the note gives its topic only, and a bracketed remark says so. Bracketed remarks also record details that differ between bibliographic databases, and the date when the online and issue years differ.

Citations were checked against Crossref and PubMed in November 2026. Author lists give every author when there are eight or fewer, and otherwise the first six followed by "et al.". Works that could not be verified, preprints and works set aside during the review are not listed.

Within each section, entries are sorted by first author's surname, then by year. A work appears once, in the section it relates to most closely; its note covers every use.

The metrics, placement sites and studies named in the notes are defined in [Model and metrics](model-and-metrics.md) and [Method details](method-details.md).

## Restricted-region and wearable EEG

These works motivate layouts confined to a low-hair area: sites around the ear, on the forehead and around the eyes.

### Ear-centred and hair-free recording systems

- Bleichner MG, Debener S (2017). Concealed, unobtrusive ear-centered EEG acquisition: cEEGrids for transparent EEG. *Frontiers in Human Neuroscience*, 11, 163. DOI: 10.3389/fnhum.2017.00163. <https://doi.org/10.3389/fnhum.2017.00163>
    - **Supports:** the premise of the low-hair area. It states that scalp caps give good coverage but are impractical in daily life, and it reviews evidence that miniature electrodes in and around the ear record continuous EEG, ERPs and oscillations.
- Debener S, Emkes R, De Vos M, Bleichner M (2015). Unobtrusive ambulatory EEG using a smartphone and flexible printed electrodes around the ear. *Scientific Reports*, 5, 16743. DOI: 10.1038/srep16743. <https://doi.org/10.1038/srep16743>
    - **Supports:** the near-postauricular and expanded periauricular sites (PL/PR, AL/AR). A ten-electrode array around the ear, worn for at least 7 hours, recovered alpha differences and P300 effects.
- Fiedler L, Wöstmann M, Graversen C, Brandmeyer A, Lunner T, Obleser J (2017). Single-channel in-ear-EEG detects the focus of auditory attention to concurrent tone streams and mixed speech. *Journal of Neural Engineering*, 14(3), 036020. DOI: 10.1088/1741-2552/aa66dd. <https://doi.org/10.1088/1741-2552/aa66dd>
    - **Supports:** ear-centred sites. A single channel formed by an in-ear electrode and an adjacent scalp electrode detected each participant's attentional focus (n = 7).
- Garrett M, Debener S, Verhulst S (2019). Acquisition of subcortical auditory potentials with around-the-ear cEEGrid technology in normal and hearing impaired listeners. *Frontiers in Neuroscience*, 13, 730. DOI: 10.3389/fnins.2019.00730. <https://doi.org/10.3389/fnins.2019.00730>
    - **Supports:** ear-centred sites. Brainstem and envelope-following responses recorded around the ear had a shape comparable to a cap montage.
    - **Limits:** the signal strength was lower than with the cap.
- Kappel SL, Rank ML, Toft HO, Andersen M, Kidmose P (2019). Dry-contact electrode ear-EEG. *IEEE Transactions on Biomedical Engineering*, 66(1), 150–158. DOI: 10.1109/TBME.2018.2835778. <https://doi.org/10.1109/TBME.2018.2835778>
    - **Supports:** dry ear-centred recording. With a common Cz reference, performance was on par with scalp EEG near the ear (12 subjects).
    - **Limits:** with in-ear references the mismatch negativity needed a reference in the opposite ear, so the reference choice matters for restricted layouts.
- Kidmose P, Looney D, Ungstrup M, Rank ML, Mandic DP (2013). A study of evoked potentials from ear-EEG. *IEEE Transactions on Biomedical Engineering*, 60(10), 2824–2830. DOI: 10.1109/TBME.2013.2264956. <https://doi.org/10.1109/TBME.2013.2264956>
    - **Supports:** ear-centred sites. Ear-EEG had a signal-to-noise ratio on par with scalp electrodes over the temporal region for auditory and visual evoked responses.
- Krigolson OE, Williams CC, Norton A, Hassall CD, Colino FL (2017). Choosing MUSE: validation of a low-cost, portable EEG system for ERP research. *Frontiers in Neuroscience*, 11, 109. DOI: 10.3389/fnins.2017.00109. <https://doi.org/10.3389/fnins.2017.00109>
    - **Supports:** the premise that a low-cost system with few dry sensors can record ERP components. It recovered the N200, P300 and reward positivity. [That the device's sensors sit on the forehead and behind the ears is device knowledge, not stated in the abstract.]
- Looney D, Kidmose P, Park C, Ungstrup M, Rank ML, Rosenkranz K, Mandic DP (2012). The in-the-ear recording concept: user-centered and wearable brain monitoring. *IEEE Pulse*, 3(6), 32–42. DOI: 10.1109/MPUL.2012.2216717. <https://doi.org/10.1109/MPUL.2012.2216717>
    - **Supports:** the premise of the low-hair area and ear-centred sites. It argues that limited portability and long setup time have held back everyday EEG, and that in-ear recording offers fixed positions, comfort and ease of use.
- Mikkelsen KB, Kappel SL, Mandic DP, Kidmose P (2015). EEG recorded from the ear: characterizing the ear-EEG method. *Frontiers in Neuroscience*, 9, 438. DOI: 10.3389/fnins.2015.00438. <https://doi.org/10.3389/fnins.2015.00438>
    - **Supports:** ear-centred sites for sources close to the ear, where ear-EEG had the same signal-to-noise ratio as scalp EEG.
    - **Limits:** referencing within the ear changed waveforms, and the auditory mismatch response was hard to monitor from the ear.
- Shustak S, Inzelberg L, Steinberg S, Rand D, David Pur M, Hillel I, et al. (2019). Home monitoring of sleep with a temporary-tattoo EEG, EOG and EMG electrode array: a feasibility study. *Journal of Neural Engineering*, 16(2), 026024. DOI: 10.1088/1741-2552/aafa05. <https://doi.org/10.1088/1741-2552/aafa05>
    - **Supports:** facial sites such as the forehead and periorbital sites (FL/FM/FR, OL/OR). A gel-free printed array on the face recorded EEG, EOG and EMG at home, with clear sleep-stage differences over a 6-hour session.
- Wang YT, Nakanishi M, Wang Y, Wei CS, Cheng CK, Jung TP (2017). An online brain-computer interface based on SSVEPs measured from non-hair-bearing areas. *IEEE Transactions on Neural Systems and Rehabilitation Engineering*, 25(1), 14–21. DOI: 10.1109/TNSRE.2016.2573819. <https://doi.org/10.1109/TNSRE.2016.2573819>
    - **Supports:** the low-hair area. Hair-covered sites need skilled technicians, skin abrasion and gel. A 12-target online interface using only non-hair-bearing sites reached 84.08 ± 15.60 % accuracy.
- Wei CS, Wang YT, Lin CT, Jung TP (2018). Toward drowsiness detection using non-hair-bearing EEG-based brain-computer interfaces. *IEEE Transactions on Neural Systems and Rehabilitation Engineering*, 26(2), 400–406. DOI: 10.1109/TNSRE.2018.2790359. <https://doi.org/10.1109/TNSRE.2018.2790359>
    - **Supports:** the low-hair area. Cross-session drowsiness detection showed no significant accuracy difference between non-hair-bearing and whole-scalp EEG.

### Comparisons with cap EEG and polysomnography

- Arnal PJ, Thorey V, Debellemaniere E, Ballard ME, Bou Hernandez A, Guillot A, et al. (2020). The Dreem Headband compared to polysomnography for electroencephalographic signal acquisition and sleep staging. *Sleep*, 43(11), zsaa097. DOI: 10.1093/sleep/zsaa097. <https://doi.org/10.1093/sleep/zsaa097>
    - **Supports:** comparing a reduced montage against a full reference. Automatic staging from a dry headband reached 83.5 ± 6.4 % accuracy against 86.4 ± 8.0 % for five expert scorers (25 subjects).
- Bleichner MG, Mirkovic B, Debener S (2016). Identifying auditory attention with ear-EEG: cEEGrid versus high-density cap-EEG comparison. *Journal of Neural Engineering*, 13(6), 066004. DOI: 10.1088/1741-2560/13/6/066004. <https://doi.org/10.1088/1741-2560/13/6/066004>
    - **Supports:** comparing an ear-centred layout with a cap recorded at the same time. Attention-modulated ERPs agreed in shape and effect size, and single-trial decoding was above chance for at least 16 of 20 participants with both systems.
- Geirnaert S, Kappel SL, Kidmose P (2025). A direct comparison of simultaneously recorded scalp, around-ear and in-ear EEG for neural selective auditory attention decoding to speech. *Scientific Reports*, 15, 41655. DOI: 10.1038/s41598-025-25576-2. <https://doi.org/10.1038/s41598-025-25576-2>
    - **Supports:** comparing restricted layouts against standard64, and adding electrodes one at a time. Adding an external reference or a few scalp electrodes by greedy forward selection raised accuracy by more than 10 percentage points.
    - **Limits:** decoding accuracy was 83.4 % for scalp, 67.2 % around the ear and 61.1 % in the ear (60-second windows). The authors describe this as a trade-off between performance and usability.
- Gu Y, Cleeren E, Dan J, Claes K, Van Paesschen W, Van Huffel S, Hunyadi B (2018). Comparison between scalp EEG and behind-the-ear EEG for development of a wearable seizure detection system for patients with focal epilepsy. *Sensors*, 18(1), 29. DOI: 10.3390/s18010029. <https://doi.org/10.3390/s18010029>
    - **Supports:** behind-the-ear sites. Seizure waveforms resembled scalp EEG, and median detection sensitivity was 94.5 % behind the ear against 100 % on the scalp (12 patients). [Published online in December 2017; the issue is dated 2018.]
- Lucey BP, McLeland JS, Toedebusch CD, Boyd J, Morris JC, Landsness EC, Yamada K, Holtzman DM (2016). Comparison of a single-channel EEG sleep study to polysomnography. *Journal of Sleep Research*, 25(6), 625–635. DOI: 10.1111/jsr.12417. <https://doi.org/10.1111/jsr.12417>
    - **Supports:** forehead sites. Epoch-by-epoch agreement with polysomnography had a kappa of 0.67.
    - **Limits:** sensitivity for stage N1 was only 0.2, which the authors attribute to the lack of occipital electrodes. Coverage of distant regions matters.
- Mikkelsen KB, Kidmose P, Hansen LK (2017). On the keyhole hypothesis: high mutual information between ear and scalp EEG. *Frontiers in Human Neuroscience*, 11, 341. DOI: 10.3389/fnhum.2017.00341. <https://doi.org/10.3389/fnhum.2017.00341>
    - **Supports:** field reconstruction retention. Linear models predicted large parts of scalp EEG from ear-EEG, and the mutual information was stable over time and mental states.
    - **Limits:** predictability was highest in the temporal regions, close to the ear.
- Mikkelsen KB, Ebajemito JK, Bonmati-Carrion MA, Santhi N, Revell VL, Atzori G, et al. (2019). Machine-learning-derived sleep-wake staging from around-the-ear electroencephalogram outperforms manual scoring and actigraphy. *Journal of Sleep Research*, 28(2), e12786. DOI: 10.1111/jsr.12786. <https://doi.org/10.1111/jsr.12786>
    - **Supports:** ear-centred sites for sleep-wake staging. [Finding not re-read; topic from the title.]
- Mikkelsen KB, Tabar YR, Kappel SL, Christensen CB, Toft HO, Hemmsen MC, et al. (2019). Accurate whole-night sleep monitoring with dry-contact ear-EEG. *Scientific Reports*, 9, 16824. DOI: 10.1038/s41598-019-53115-3. <https://doi.org/10.1038/s41598-019-53115-3>
    - **Supports:** dry ear-centred recording. Automatic scoring from ear-EEG alone reached a mean kappa of 0.73 over 80 nights, close to manual scalp scoring, and participants could generally apply the device unsupervised.
- Mirkovic B, Bleichner MG, De Vos M, Debener S (2016). Target speaker detection with concealed EEG around the ear. *Frontiers in Neuroscience*, 10, 349. DOI: 10.3389/fnins.2016.00349. <https://doi.org/10.3389/fnins.2016.00349>
    - **Supports:** comparing an ear-centred layout with a cap recorded at the same time.
    - **Limits:** the attended speaker was identified with 69.3 % accuracy around the ear against 84.8 % with the cap (20 listeners).
- Sterr A, Ebajemito JK, Mikkelsen KB, Bonmati-Carrion MA, Santhi N, della Monica C, et al. (2018). Sleep EEG derived from behind-the-ear electrodes (cEEGrid) compared to standard polysomnography: a proof of concept study. *Frontiers in Human Neuroscience*, 12, 452. DOI: 10.3389/fnhum.2018.00452. <https://doi.org/10.3389/fnhum.2018.00452>
    - **Supports:** behind-the-ear sites. The array was judged comfortable, simple to apply and a viable tool to capture sleep and wake EEG.
    - **Limits:** the authors call for further validation.
- Zibrandtsen IC, Kidmose P, Christensen CB, Kjaer TW (2017). Ear-EEG detects ictal and interictal abnormalities in focal and generalized epilepsy – a comparison with scalp EEG monitoring. *Clinical Neurophysiology*, 128(12), 2454–2461. DOI: 10.1016/j.clinph.2017.09.115. <https://doi.org/10.1016/j.clinph.2017.09.115>
    - **Supports:** ear-centred sites. Seizure-detection sensitivity and specificity did not differ from scalp EEG (15 patients).
    - **Limits:** the correlation with scalp channels fell with distance from the ear, and interictal spikes were visible only from large temporal sources.

### Forward models of ear-centred arrays

- Kappel SL, Makeig S, Kidmose P (2019). Ear-EEG forward models: improved head-models for ear-EEG. *Frontiers in Neuroscience*, 13, 943. DOI: 10.3389/fnins.2019.00943. <https://doi.org/10.3389/fnins.2019.00943>
    - **Supports:** evaluating ear-centred layouts with forward models. The models can be used to explore the sensitivity of different ear electrode configurations to brain sources.
    - **Limits:** existing head models do not describe the external ear well; the authors added 3D-scanned ear anatomy for four subjects.
- Meiser A, Tadel F, Debener S, Bleichner MG (2020). The sensitivity of ear-EEG: evaluating the source-sensor relationship using forward modeling. *Brain Topography*, 33(6), 665–676. DOI: 10.1007/s10548-020-00793-2. <https://doi.org/10.1007/s10548-020-00793-2>
    - **Supports:** forward-model evaluation of ear-centred arrays. It studies how sensitive arrays around the ear are to source position and orientation. EEGLayoutLab also examines fixed 64-electrode layouts, region size and field reconstruction.
- Meiser A, Knoll AL, Bleichner MG (2024). High-density ear-EEG for understanding ear-centered EEG. *Journal of Neural Engineering*, 21(1), 016001. DOI: 10.1088/1741-2552/ad1783. <https://doi.org/10.1088/1741-2552/ad1783>
    - **Supports:** dense sampling around the ear. It studies two-dimensional sampling with 31 electrodes around one ear and shows the additional information that several contacts provide.
    - **Limits:** its array covers only the area around the ear.
- Yarici MC, Thornton M, Mandic DP (2023). Ear-EEG sensitivity modeling for neural sources and ocular artifacts. *Frontiers in Neuroscience*, 16, 997377. DOI: 10.3389/fnins.2022.997377. <https://doi.org/10.3389/fnins.2022.997377>
    - **Supports:** forward-model evaluation of ear-centred arrays and the EOG model in signal simulation. It models the sensitivity of several ear configurations to neural sources and to blink and saccade sources. The results support ear-EEG for temporal-lobe activity and show how far more distant sources can be measured. [Crossref dates the article 9 January 2023; the volume is dated 2022.]

### Reviews, wearable systems and dry electrodes

- Casson AJ (2019). Wearable EEG and beyond. *Biomedical Engineering Letters*, 9(1), 53–71. DOI: 10.1007/s13534-018-00093-6. <https://doi.org/10.1007/s13534-018-00093-6>
    - **Supports:** the premise of wearable restricted layouts. Conventional EEG is bulky and tied to stationary subjects. The review names validation standards for new electrodes as the main bottleneck.
- Chi YM, Jung TP, Cauwenberghs G (2010). Dry-contact and noncontact biopotential electrodes: methodological review. *IEEE Reviews in Biomedical Engineering*, 3, 106–119. DOI: 10.1109/RBME.2010.2084078. <https://doi.org/10.1109/RBME.2010.2084078>
    - **Supports:** the premise of the low-hair area. Wet electrodes give excellent signals but are cumbersome for mobile use; the review covers the performance limits of dry and noncontact electrodes.
- Geirnaert S, Vandecappelle S, Alickovic E, de Cheveigné A, Lalor E, Meyer BT, et al. (2021). Electroencephalography-based auditory attention decoding: toward neurosteered hearing devices. *IEEE Signal Processing Magazine*, 38(4), 89–102. DOI: 10.1109/MSP.2021.3075932. <https://doi.org/10.1109/MSP.2021.3075932>
    - **Supports:** the application context of ear-centred layouts, EEG-based attention decoding for hearing devices. [Finding not re-read; topic from the title and venue.]
- Hua H, Tang W, Xu X, Feng DD, Shu L (2019). Flexible multi-layer semi-dry electrode for scalp EEG measurements at hairy sites. *Micromachines*, 10(8), 518. DOI: 10.3390/mi10080518. <https://doi.org/10.3390/mi10080518>
    - **Supports:** the low-hair area and the unequal contact noise model. Suitable electrodes for hairy sites are rare, wet gels dry out, and most dry electrodes have inadequate impedance at hairy sites. The authors' semi-dry design reached 23.89 ± 7.44 kΩ at 10 Hz on a hairy site.
- Kaongoen N, Choi J, Choi JW, Kwon H, Hwang C, Hwang G, Kim BH, Jo S (2023). The future of wearable EEG: a review of ear-EEG technology and its applications. *Journal of Neural Engineering*, 20(5), 051002. DOI: 10.1088/1741-2552/acfcda. <https://doi.org/10.1088/1741-2552/acfcda>
    - **Supports:** ear-centred sites. A review of 123 ear-EEG publications concludes that ear-EEG gives results comparable to scalp EEG, and it discusses the limitations relative to scalp EEG. [Crossref lists the third author as "Woo Choi, Jin"; cited here as Choi JW.]
- Lopez-Gordo MA, Sanchez-Morillo D, Pelayo Valle F (2014). Dry EEG electrodes. *Sensors*, 14(7), 12847–12870. DOI: 10.3390/s140712847. <https://doi.org/10.3390/s140712847>
    - **Supports:** the premise of gel-free wearable layouts. Usability and gel-free operation are now first-order priorities.
    - **Limits:** methods for evaluating dry electrodes lack consensus. [Crossref lists the authors as Lopez-Gordo M, Sanchez-Morillo D, Valle F.]
- Mihai (Ungureanu) AS, Geman O, Toderean R, Miron L, SharghiLavan S (2025). The next frontier in brain monitoring: a comprehensive look at in-ear EEG electrodes and their applications. *Sensors*, 25(11), 3321. DOI: 10.3390/s25113321. <https://doi.org/10.3390/s25113321>
    - **Supports:** ear-centred sites. The review compares in-ear EEG with scalp EEG on signal-to-noise ratio, common-mode rejection, amplitude and comfort, and discusses its limits. [Crossref gives the first author as "Mihai (Ungureanu), Alexandra Stefania"; Europe PMC indexes her as Mihai Ungureanu AS.]
- Mullen TR, Kothe CAE, Chi YM, Ojeda A, Kerth T, Makeig S, Jung TP, Cauwenberghs G (2015). Real-time neuroimaging and cognitive monitoring using wearable dry EEG. *IEEE Transactions on Biomedical Engineering*, 62(11), 2553–2567. DOI: 10.1109/TBME.2015.2481482. <https://doi.org/10.1109/TBME.2015.2481482>
    - **Supports:** the combination of wearable hardware with a forward model. It pairs a 64-channel dry headset with forward-model-based real-time source imaging.
    - **Limits:** it does not design or compare layouts.
- Niso G, Romero E, Moreau JT, Araujo A, Krol LR (2023). Wireless EEG: a survey of systems and studies. *NeuroImage*, 269, 119774. DOI: 10.1016/j.neuroimage.2022.119774. <https://doi.org/10.1016/j.neuroimage.2022.119774>
    - **Supports:** the context for restricted layouts. The survey catalogues 48 wireless EEG devices and 110 high-impact studies, and describes the move toward miniaturized hardware and use outside the laboratory.
- Sugden RJ, Pham-Kim-Nghiem-Phu VLL, Campbell I, Leon A, Diamandis P (2023). Remote collection of electrophysiological data with brain wearables: opportunities and challenges. *Bioelectronic Medicine*, 9(1), 12. DOI: 10.1186/s42234-023-00114-5. <https://doi.org/10.1186/s42234-023-00114-5>
    - **Supports:** the context for restricted layouts. Low-cost wearable EEG gives usable data for remote, longitudinal collection, with challenges to adoption remaining.
- Wang Z, Ding Y, Yuan W, Chen H, Chen W, Chen C (2024). Active claw-shaped dry electrodes for EEG measurement in hair areas. *Bioengineering*, 11(3), 276. DOI: 10.3390/bioengineering11030276. <https://doi.org/10.3390/bioengineering11030276>
    - **Supports:** the low-hair area and the unequal contact noise model. Dry-electrode contact impedance is high and unstable, especially in hair-covered areas. [Impedance figures not re-read in the full text.]

## Spatial sampling and scalp coverage

These works show that both the density and the coverage of an array set what it can recover. They support comparing restricted layouts with standard64 on coverage, not only on channel count.

### Sampling density and spatial frequency

- Freeman WJ, Holmes MD, Burke BC, Vanhatalo S (2003). Spatial spectra of scalp EEG and EMG from awake humans. *Clinical Neurophysiology*, 114(6), 1053–1068. DOI: 10.1016/S1388-2457(03)00045-2. <https://doi.org/10.1016/S1388-2457(03)00045-2>
    - **Supports:** treating spacing as part of the sampling question. Linear arrays at 3 mm pitch on the forehead and occiput suggested an optimal spacing of about 1 cm for gyral-scale detail.
    - **Limits:** EMG contaminates scalp EEG on the forehead itself, and filtering is an unsatisfactory remedy. Muscle noise at forehead and periorbital sites is not represented by the `spatial` or `brain_background` noise models.
- Graichen U, Eichardt R, Fiedler P, Strohmeier D, Zanow F, Haueisen J (2015). SPHARA – a generalized spatial Fourier analysis for multi-sensor systems with non-uniformly arranged sensors: application to EEG. *PLOS ONE*, 10(4), e0121741. DOI: 10.1371/journal.pone.0121741. <https://doi.org/10.1371/journal.pone.0121741>
    - **Supports:** field reconstruction retention as an explained-energy measure. On non-uniform EEG meshes, 35 % and 58 % of the spatial coefficients recovered 95 % and 99 % of the energy of somatosensory evoked potentials.
- Grieve PG, Emerson RG, Isler JR, Stark RI (2004). Quantitative analysis of spatial sampling error in the infant and adult electroencephalogram. *NeuroImage*, 21(4), 1260–1274. DOI: 10.1016/j.neuroimage.2003.11.028. <https://doi.org/10.1016/j.neuroimage.2003.11.028>
    - **Supports:** field reconstruction retention and the 20 dB nominal SNR. Reconstruction error with noise is an established way to score arrays. Without noise, 64 evenly spaced electrodes gave less than 10 % sampling error in adults.
    - **Limits:** with noise at one tenth of EEG power, the 64-electrode error rose to about 25 %. Reconstruction cannot remove the noise floor.
- Grover P, Venkatesh P (2017). An information-theoretic view of EEG sensing. *Proceedings of the IEEE*, 105(2), 367–384. DOI: 10.1109/JPROC.2016.2615179. <https://doi.org/10.1109/JPROC.2016.2615179>
    - **Supports:** keeping field reconstruction retention and the relative localization score as separate metrics. The minimum sensor count for reconstructing the scalp field within a given error is a different question from localizing sources, and it needs noise included.
    - **Limits:** the authors argue that strong spatial correlation can cut sampling cost, so spacing limits based on scalp reconstruction do not bound localization.
- Iivanainen J, Mäkinen AJ, Zetter R, Stenroos M, Ilmoniemi RJ, Parkkonen L (2021). Spatial sampling of MEG and EEG based on generalized spatial-frequency analysis and optimal design. *NeuroImage*, 245, 118747. DOI: 10.1016/j.neuroimage.2021.118747. <https://doi.org/10.1016/j.neuroimage.2021.118747>
    - **Supports:** forward-model-based, information-based evaluation of layouts, the closest precedent for the approach. EEG in a realistic head can benefit from up to about 110 spatial samples. With few samples, model-informed non-uniform sampling helps; with many, uniform grids give nearly the same total information.
- Lantz G, Grave de Peralta R, Spinelli L, Seeck M, Michel CM (2003). Epileptic source localization with high density EEG: how many electrodes are needed? *Clinical Neurophysiology*, 114(1), 63–69. DOI: 10.1016/S1388-2457(02)00337-1. <https://doi.org/10.1016/S1388-2457(02)00337-1>
    - **Supports:** the relative localization score. In 14 patients, localization was closer to the lesion with 63 than with 31 channels in 9 patients, and 123 channels raised this to 11.
- Robinson AK, Venkatesh P, Boring MJ, Tarr MJ, Grover P, Behrmann M (2017). Very high density EEG elucidates spatiotemporal aspects of early visual processing. *Scientific Reports*, 7, 16248. DOI: 10.1038/s41598-017-16377-3. <https://doi.org/10.1038/s41598-017-16377-3>
    - **Supports:** dense regional arrays. A 128-electrode array at 14 mm spacing over occipitotemporal cortex classified stimuli more accurately than sparser subsets of the same electrodes.
    - **Limits:** a fixed spacing is not a hard ceiling on useful density.
- Ryynänen ORM, Hyttinen JAK, Laarne PH, Malmivuo JA (2004). Effect of electrode density and measurement noise on the spatial resolution of cortical potential distribution. *IEEE Transactions on Biomedical Engineering*, 51(9), 1547–1554. DOI: 10.1109/TBME.2004.828036. <https://doi.org/10.1109/TBME.2004.828036>
    - **Supports:** a fixed nominal SNR for a fair comparison of layouts, and a 64-channel reference. The benefit of dense arrays shrinks as noise grows; in clinical settings at least 64 electrodes are always beneficial.
- Ryynänen ORM, Hyttinen JAK, Malmivuo JA (2006). Effect of measurement noise and electrode density on the spatial resolution of cortical potential distribution with different resistivity values for the skull. *IEEE Transactions on Biomedical Engineering*, 53(9), 1851–1858. DOI: 10.1109/TBME.2006.873744. <https://doi.org/10.1109/TBME.2006.873744>
    - **Supports:** the skull ×0.5 and ×2 conductivity scenarios.
    - **Limits:** conclusions about density depend on skull resistivity, so results hold for the conductivities of the head model used.
- Sohrabpour A, Lu Y, Kankirawatana P, Blount J, Kim H, He B (2015). Effect of EEG electrode number on epileptic source localization in pediatric patients. *Clinical Neurophysiology*, 126(3), 472–480. DOI: 10.1016/j.clinph.2014.05.038. <https://doi.org/10.1016/j.clinph.2014.05.038>
    - **Supports:** the relative localization score and amplitude retention (worst 10%). Localization improves with electrode number, with a shrinking gain per electrode, and more electrodes help most for deep sources.
- Srinivasan R, Tucker DM, Murias M (1998). Estimating the spatial Nyquist of the human EEG. *Behavior Research Methods, Instruments, & Computers*, 30(1), 8–19. DOI: 10.3758/BF03209412. <https://doi.org/10.3758/BF03209412>
    - **Supports:** the framing of spatial sampling: the spatial Nyquist estimate for full-head EEG. [Full text and abstract not available for checking; the spacing figure is not stated here.]
- Tucker DM (1993). Spatial sampling of head electrical fields: the geodesic sensor net. *Electroencephalography and Clinical Neurophysiology*, 87(3), 154–163. DOI: 10.1016/0013-4694(93)90121-B. <https://doi.org/10.1016/0013-4694(93)90121-B>
    - **Supports:** treating coverage and density together. It argues that the ideal measurement samples the whole braincase densely enough to avoid spatial aliasing.

### Coverage, inferior electrodes and targeted placement

- Bach Justesen A, Eskelund Johansen AB, Martinussen NI, Wasserman D, Terney D, Meritam P, Gardella E, Beniczky S (2018). Added clinical value of the inferior temporal EEG electrode chain. *Clinical Neurophysiology*, 129(1), 291–295. DOI: 10.1016/j.clinph.2017.09.113. <https://doi.org/10.1016/j.clinph.2017.09.113>
    - **Supports:** coverage as distinct from density. Of 286 abnormal recordings, 28.3 % peaked at inferior temporal electrodes and 2.8 % were visible only there.
- Brodbeck V, Spinelli L, Lascano AM, Wissmeier M, Vargas MI, Vulliemoz S, et al. (2011). Electroencephalographic source imaging: a prospective study of 152 operated epileptic patients. *Brain*, 134(10), 2887–2897. DOI: 10.1093/brain/awr243. <https://doi.org/10.1093/brain/awr243>
    - **Supports:** the relative localization score and the use of more than one head model. With 128–256 channels and individual head models, sensitivity was 84 % and specificity 88 %; with fewer than 32 channels and a template head they fell to 57 % and 59 %.
- Horrillo-Maysonnial A, Avigdor T, Abdallah C, Mansilla D, Thomas J, von Ellenrieder N, et al. (2023). Targeted density electrode placement achieves high concordance with traditional high-density EEG for electrical source imaging in epilepsy. *Clinical Neurophysiology*, 156, 262–271. DOI: 10.1016/j.clinph.2023.08.009. <https://doi.org/10.1016/j.clinph.2023.08.009>
    - **Supports:** placement as a substitute for count for a known region. The 25 standard electrodes plus 8–11 placed around the spike maximum gave a median peak distance of 13.2 mm from 83-channel EEG across 58 foci.
    - **Limits:** tangential generators fared worse, and the placement depends on knowing the source in advance.
- Liu Q, Ganzetti M, Wenderoth N, Mantini D (2018). Detecting large-scale brain networks using EEG: impact of electrode density, head modeling and source localization. *Frontiers in Neuroinformatics*, 12, 4. DOI: 10.3389/fninf.2018.00004. <https://doi.org/10.3389/fninf.2018.00004>
    - **Supports:** reporting layout results together with the head model. Detecting resting-state networks depends strongly on electrode density, and head modelling and the source method also have a substantial effect.
- Michel CM, Brunet D (2019). EEG source imaging: a practical review of the analysis steps. *Frontiers in Neurology*, 10, 325. DOI: 10.3389/fneur.2019.00325. <https://doi.org/10.3389/fneur.2019.00325>
    - **Supports:** coverage as well as density. Arrays with fewer than 32 sensors cause mislocalization, and the 10-20 system lacks inferior electrodes, so the review recommends at least three inferior electrodes per side.
- Seeck M, Koessler L, Bast T, Leijten F, Michel C, Baumgartner C, He B, Beniczky S (2017). The standardized EEG electrode array of the IFCN. *Clinical Neurophysiology*, 128(10), 2070–2077. DOI: 10.1016/j.clinph.2017.06.254. <https://doi.org/10.1016/j.clinph.2017.06.254>
    - **Supports:** coverage as a requirement. The guideline notes that standard recordings miss the anterior and basal temporal lobes and defines a 25-electrode array that includes the inferior temporal chain.
- Song J, Davey C, Poulsen C, Luu P, Turovets S, Anderson E, Li K, Tucker D (2015). EEG source localization: sensor density and head surface coverage. *Journal of Neuroscience Methods*, 256, 9–21. DOI: 10.1016/j.jneumeth.2015.08.015. <https://doi.org/10.1016/j.jneumeth.2015.08.015>
    - **Supports:** comparing layouts by coverage. It studies how electrode density and head-surface coverage affect localization.
- Vorderwülbecke BJ, Carboni M, Tourbier S, Brunet D, Seeber M, Spinelli L, Seeck M, Vulliemoz S (2020). High-density electric source imaging of interictal epileptic discharges: how many electrodes and which time point? *Clinical Neurophysiology*, 131(12), 2795–2803. DOI: 10.1016/j.clinph.2020.09.018. <https://doi.org/10.1016/j.clinph.2020.09.018>
    - **Limits:** more inferior coverage is not always better. Removing cheek and neck electrodes from 257 to 204 channels gave the most accurate localization in 45 patients; the lowest channels carried more artefact. Sites near the ear share this lower-head position.

## Field reconstruction, interpolation and estimators

These works relate to field reconstruction retention: estimating the standard64 field from another layout with the LMMSE estimator, and the alternatives to it.

- Corley IA, Huang Y (2018). Deep EEG super-resolution: upsampling EEG spatial resolution with generative adversarial networks. In: *2018 IEEE EMBS International Conference on Biomedical & Health Informatics (BHI)*, pp. 100–103. IEEE. DOI: 10.1109/BHI.2018.8333379. <https://doi.org/10.1109/BHI.2018.8333379>
    - **Supports:** reconstruction of missing channels as a scored problem, here without a forward model. A generative network gave lower error than bicubic interpolation.
    - **Limits:** the baseline is weak; it is neither splines nor a forward-model estimator.
- Dale AM, Sereno MI (1993). Improved localization of cortical activity by combining EEG and MEG with MRI cortical surface reconstruction: a linear approach. *Journal of Cognitive Neuroscience*, 5(2), 162–176. DOI: 10.1162/jocn.1993.5.2.162. <https://doi.org/10.1162/jocn.1993.5.2.162>
    - **Supports:** the structure of the LMMSE estimator. It derives the optimal linear inverse operator for a given cortical surface, sensor placement, noise covariance and source prior, with fixed orientations normal to the cortex. [Crossref's title field reads "Localizadon"; the printed title is used here.]
- Hämäläinen MS, Ilmoniemi RJ (1994). Interpreting magnetic fields of the brain: minimum norm estimates. *Medical & Biological Engineering & Computing*, 32(1), 35–42. DOI: 10.1007/BF02512476. <https://doi.org/10.1007/BF02512476>
    - **Supports:** forward-model-based virtual channels. The abstract notes that the estimated currents can also serve to interpolate and extrapolate the measured field, and that more measurements make the estimate more localized.
- Hu S, Yao D, Valdes-Sosa PA (2018). Unified Bayesian estimator of EEG reference at infinity: rREST (regularized reference electrode standardization technique). *Frontiers in Neuroscience*, 12, 297. DOI: 10.3389/fnins.2018.00297. <https://doi.org/10.3389/fnins.2018.00297>
    - **Supports:** the LMMSE estimator and the reference-free comparison. It is a peer-reviewed precedent for using a Gaussian lead-field prior and a noise-variance ratio to reconstruct a standardized scalp field; the average reference corresponds to a non-informative prior.
- Kim H, Luo J, Chu S, Cannard C, Hoffmann S, Miyakoshi M (2023). ICA's bug: how ghost ICs emerge from effective rank deficiency caused by EEG electrode interpolation and incorrect re-referencing. *Frontiers in Signal Processing*, 3, 1064138. DOI: 10.3389/frsip.2023.1064138. <https://doi.org/10.3389/frsip.2023.1064138>
    - **Supports:** treating interpolated channels as estimates. Interpolation and re-referencing reduce the effective rank below the channel count, so a layout's information is bounded by its measured, reference-free dimensions.
- Knösche TR (2002). Transformation of whole-head MEG recordings between different sensor positions. *Biomedizinische Technik / Biomedical Engineering*, 47(3), 59–62. DOI: 10.1515/bmte.2002.47.3.59. <https://doi.org/10.1515/bmte.2002.47.3.59>
    - **Supports:** reconstructing the field of a reference layout from a different layout, an established operation in MEG. The method was robust in simulations and phantom recordings even with large position differences and high noise.
- Kwon M, Han S, Kim K, Jun SC (2019). Super-resolution for improving EEG spatial resolution using deep convolutional neural network—feasibility study. *Sensors*, 19(23), 5317. DOI: 10.3390/s19235317. <https://doi.org/10.3390/s19235317>
    - **Supports:** field upsampling as a scored reconstruction problem. A convolutional network gave lower error and more plausible localization than the low-resolution data.
- Li D, Zeng Z, Wang Z, Yang H (2025). ESTformer: transformer utilising spatiotemporal dependencies for electroencephalogram super-resolution. *Knowledge-Based Systems*, 317, 113345. DOI: 10.1016/j.knosys.2025.113345. <https://doi.org/10.1016/j.knosys.2025.113345>
    - **Supports:** channel reconstruction as an active benchmark problem. A transformer outperformed earlier methods on two datasets; it has no forward-model prior.
- Perrin F, Pernier J, Bertrand O, Echallier JF (1989). Spherical splines for scalp potential and current density mapping. *Electroencephalography and Clinical Neurophysiology*, 72(2), 184–187. DOI: 10.1016/0013-4694(89)90180-6. <https://doi.org/10.1016/0013-4694(89)90180-6>
    - **Supports:** the standard interpolation baseline. Spherical splines are faster and more accurate than thin-plate splines where electrodes are sparse. They use a smoothness prior with no forward model or noise model, which motivates a forward-model estimator.
- Svantesson M, Olausson H, Eklund A, Thordstein M (2021). Virtual EEG-electrodes: convolutional neural networks as a method for upsampling or restoring channels. *Journal of Neuroscience Methods*, 355, 109126. DOI: 10.1016/j.jneumeth.2021.109126. <https://doi.org/10.1016/j.jneumeth.2021.109126>
    - **Supports:** a statistical prior over a smoothness prior. Networks trained on 1,385 subjects significantly outperformed spherical splines when upsampling to 21 channels.
    - **Limits:** interpolation works better at higher densities, and values far from the electrodes can be unreliable. This bounds what a restricted layout can say about distant parts of the field.

## Reference choice

These works support comparing layouts in the reference-free space, with the common reference removed by Helmert contrasts, instead of under any one reference.

- Dong L, Li F, Liu Q, Wen X, Lai Y, Xu P, Yao D (2017). MATLAB toolboxes for reference electrode standardization technique (REST) of scalp EEG. *Frontiers in Neuroscience*, 11, 601. DOI: 10.3389/fnins.2017.00601. <https://doi.org/10.3389/fnins.2017.00601>
    - **Supports:** background on re-referencing tools. It provides open-source toolboxes that re-reference recordings to an approximate reference at infinity.
- Ferree TC (2006). Spherical splines and average referencing in scalp electroencephalography. *Brain Topography*, 19(1–2), 43–52. DOI: 10.1007/s10548-006-0011-0. <https://doi.org/10.1007/s10548-006-0011-0>
    - **Supports:** the reference-free comparison. Average-referenced potentials carry errors from incomplete scalp sampling that persist at high density, because the inferior scalp is not sampled.
    - **Limits:** spline estimates beat the average reference only when the sampling density is adequate.
- Geselowitz DB (1998). The zero of potential. *IEEE Engineering in Medicine and Biology Magazine*, 17(1), 128–132. DOI: 10.1109/51.646230. <https://doi.org/10.1109/51.646230>
    - **Supports:** the reference-free comparison. In a bounded volume conductor no point has true zero potential, and the choice of reference changes only an additive constant, not the information in the potential distribution.
- Hu S, Lai Y, Valdes-Sosa PA, Bringas-Vega ML, Yao D (2018). How do reference montage and electrodes setup affect the measured scalp EEG potentials? *Journal of Neural Engineering*, 15(2), 026013. DOI: 10.1088/1741-2552/aaa13f. <https://doi.org/10.1088/1741-2552/aaa13f>
    - **Supports:** removing the reference from the comparison. The accuracy of the average reference depends on electrode coverage and dipole orientation, so it is not neutral for restricted layouts; linked mastoids performed worst.
- Junghöfer M, Elbert T, Tucker DM, Braun C (1999). The polar average reference effect: a bias in estimating the head surface integral in EEG recording. *Clinical Neurophysiology*, 110(6), 1149–1155. DOI: 10.1016/S1388-2457(99)00044-9. <https://doi.org/10.1016/S1388-2457(99)00044-9>
    - **Supports:** the reference-free comparison for region-confined layouts. The average reference approximates an inactive reference only with dense, full-head sampling; electrodes concentrated in one region bias the average toward that region.
- Nunez PL, Srinivasan R (2006). *Electric Fields of the Brain: The Neurophysics of EEG* (2nd ed.). New York: Oxford University Press. ISBN 978-0-19-505038-7. DOI: 10.1093/acprof:oso/9780195050387.001.0001. <https://doi.org/10.1093/acprof:oso/9780195050387.001.0001>
    - **Supports:** background on volume conduction, reference choice, high-resolution EEG and spatial sampling.
- Nunez PL (2010). REST: a good idea but not the gold standard. *Clinical Neurophysiology*, 121(12), 2177–2180. DOI: 10.1016/j.clinph.2010.04.029. <https://doi.org/10.1016/j.clinph.2010.04.029>
    - **Supports:** not treating any reference as the truth. The commentary argues that REST should not be treated as the gold standard, since no reference site is free of local sources.
- Yao D (2001). A method to standardize a reference of scalp EEG recordings to a point at infinity. *Physiological Measurement*, 22(4), 693–711. DOI: 10.1088/0967-3334/22/4/305. <https://doi.org/10.1088/0967-3334/22/4/305>
    - **Supports:** the reference-free comparison and reconstruction through a forward model. Finding equivalent sources from scalp potentials does not depend on the reference.
- Yao D, Qin Y, Hu S, Dong L, Bringas Vega ML, Valdés Sosa PA (2019). Which reference should we use for EEG and ERP practice? *Brain Topography*, 32(4), 530–549. DOI: 10.1007/s10548-019-00707-x. <https://doi.org/10.1007/s10548-019-00707-x>
    - **Supports:** the reference-free comparison. No body point has zero or constant potential, so more than ten references are in use, each resting on different assumptions.

## Sensor array design and channel selection

These works treat the choice of sensor positions or channels as an optimization problem. They relate to the local radius search, Pareto ranking in the result library and channel subsets from recordings.

### EEG electrode selection with forward models

- Mosher JC, Spencer ME, Leahy RM, Lewis PS (1993). Error bounds for EEG and MEG dipole source localization. *Electroencephalography and Clinical Neurophysiology*, 86(5), 303–321. DOI: 10.1016/0013-4694(93)90043-U. <https://doi.org/10.1016/0013-4694(93)90043-U>
    - **Supports:** judging arrays by bounds on dipole-localization error, background to the relative localization score. [Finding not re-read; topic from the title.]
- Soler A, Giraldo E, Lundheim L, Molinas M (2022). Relevance-based channel selection for EEG source reconstruction: an approach to identify low-density channel subsets. In: *Proceedings of the 15th International Joint Conference on Biomedical Engineering Systems and Technologies (BIOSTEC 2022) – Volume 2: BIOSTEC / BIOIMAGING*, pp. 174–183. SciTePress. ISBN 978-989-758-552-4. DOI: 10.5220/0010907100003123. <https://doi.org/10.5220/0010907100003123>
    - **Supports:** selecting small electrode subsets with a forward model. Subsets of 6 and 9 channels chosen by relevance reconstructed sources comparably to 128 distributed channels and better than 62 standard 10-10 channels. [Pages from the publisher's page; Crossref gives none.]
- Soler A, Moctezuma LA, Giraldo E, Molinas M (2022). Automated methodology for optimal selection of minimum electrode subsets for accurate EEG source estimation based on genetic algorithm optimization. *Scientific Reports*, 12, 11221. DOI: 10.1038/s41598-022-15252-0. <https://doi.org/10.1038/s41598-022-15252-0>
    - **Supports:** electrode-subset search as an established problem and Pareto ranking. A multi-objective search minimized localization error and electrode count together; for one source, optimal 6-electrode subsets matched or beat more than 200 channels in over 88 % of synthetic and 63 % of real cases.
    - **Limits:** subsets were optimized per known source, so they show source-specific rather than general adequacy. EEGLayoutLab scores reconstruction of the whole field instead.
- Soler A, Giraldo E, Molinas M (2024). EEG source imaging of hand movement-related areas: an evaluation of the reconstruction and classification accuracy with optimized channels. *Brain Informatics*, 11(1), 11. DOI: 10.1186/s40708-024-00224-z. <https://doi.org/10.1186/s40708-024-00224-z>
    - **Supports:** optimized channel subsets for a target region. From 339 channels, localization error was 3.99, 10.69 and 14.29 mm with 32, 16 and 8 optimized channels, and 16 optimized channels outperformed 32 standard 10-10 electrodes in motor-imagery classification.

### MEG and OPM arrays

- Beltrachini L, von Ellenrieder N, Eichardt R, Haueisen J (2021). Optimal design of on-scalp electromagnetic sensor arrays for brain source localisation. *Human Brain Mapping*, 42(15), 4869–4879. DOI: 10.1002/hbm.25586. <https://doi.org/10.1002/hbm.25586>
    - **Supports:** forward-model-based array design. Arrays are designed by minimizing the Cramér-Rao bound on localization error, which holds for any estimator, including nearly optimal positions for a limited number of sensors over a target region.
- Iivanainen J, Stenroos M, Parkkonen L (2017). Measuring MEG closer to the brain: performance of on-scalp sensor arrays. *NeuroImage*, 147, 542–553. DOI: 10.1016/j.neuroimage.2016.12.048. <https://doi.org/10.1016/j.neuroimage.2016.12.048>
    - **Supports:** comparing arrays with forward models from several heads (10 adults) on signal power, field-pattern correlation and information capacity.
- Kemppainen PK, Ilmoniemi RJ (1989). Channel capacity of multichannel magnetometers. In: Williamson SJ, Hoke M, Stroink G, Kotani M (eds.), *Advances in Biomagnetism*, pp. 635–638. Springer US. ISBN 978-1-4612-7876-4. DOI: 10.1007/978-1-4613-0581-1_141. <https://doi.org/10.1007/978-1-4613-0581-1_141>
    - **Supports:** information-based comparison of array designs. [Finding not re-read; topic from the title.]
- Marhl U, Hren R, Sander T, Jazbinšek V (2025). Optimization of OPM-MEG layouts with a limited number of sensors. *Sensors*, 25(9), 2706. DOI: 10.3390/s25092706. <https://doi.org/10.3390/s25092706>
    - **Supports:** choosing sensors that best reconstruct a full-head field, the same aim as field reconstruction retention. The first 15–20 sensors chosen reached a correlation above 0.95 with the full map.
- Marhl U, Hren R, Sander T, Jazbinšek V (2026). Optimizing OPM-MEG sensor layouts using the sequential selection algorithm with simulated sources and individual anatomy. *Sensors*, 26(4), 1292. DOI: 10.3390/s26041292. <https://doi.org/10.3390/s26041292>
    - **Supports:** designing layouts from simulated forward fields instead of measurements. Layouts from individual-MRI forward models were comparable to those from measured data and needed fewer sensors.
- Nenonen J, Taulu S, Kajola M, Ahonen A (2007). Total information extracted from MEG measurements. *International Congress Series*, 1300, 245–248. DOI: 10.1016/j.ics.2007.01.058. <https://doi.org/10.1016/j.ics.2007.01.058>
    - **Supports:** information-based comparison of array designs. [Finding not re-read; topic from the title.]
- Nurminen J, Taulu S, Nenonen J, Helle L, Simola J, Ahonen A (2013). Improving MEG performance with additional tangential sensors. *IEEE Transactions on Biomedical Engineering*, 60(9), 2559–2566. DOI: 10.1109/TBME.2013.2260541. <https://doi.org/10.1109/TBME.2013.2260541>
    - **Supports:** evaluating an array change by its effect on reconstruction. Adding tangential sensors to break the symmetry of a 306-channel array reduced residual reconstruction noise by 20 %.
- Riaz B, Pfeiffer C, Schneiderman JF (2017). Evaluation of realistic layouts for next generation on-scalp MEG: spatial information density maps. *Scientific Reports*, 7, 6974. DOI: 10.1038/s41598-017-07046-6. <https://doi.org/10.1038/s41598-017-07046-6>
    - **Supports:** mapping over the source space what an array extracts, as the per-source metrics do. It compares three on-scalp layouts with a commercial array.
- Schneiderman JF (2014). Information content with low- vs. high-Tc SQUID arrays in MEG recordings: the case for high-Tc SQUID-based MEG. *Journal of Neuroscience Methods*, 222, 42–46. DOI: 10.1016/j.jneumeth.2013.10.007. <https://doi.org/10.1016/j.jneumeth.2013.10.007>
    - **Supports:** information content as a figure of merit for arrays. A high-Tc array extracted at least 40 % more information than an equivalent low-Tc array despite higher sensor noise.
- Schoffelen JM, Cheung T, Knappe S, Oostenveld R (2025). Optimal configuration of on-scalp OPMs with fixed channel counts. *Imaging Neuroscience*, 3, IMAG.a.22. DOI: 10.1162/imag.a.22. <https://doi.org/10.1162/imag.a.22>
    - **Supports:** comparing layouts at a fixed channel count, as EEGLayoutLab does with 64 electrodes.
    - **Limits:** the ranking with sensor noise only changed under movement and ambient noise. Rankings can depend on the noise model.
- Takeda Y, Gomi T, Umebayashi R, Tomita S, Suzuki K, Hiroe N, et al. (2023). Sensor array design of optically pumped magnetometers for accurately estimating source currents. *NeuroImage*, 277, 120257. DOI: 10.1016/j.neuroimage.2023.120257. <https://doi.org/10.1016/j.neuroimage.2023.120257>
    - **Supports:** sequential sensor placement against a forward model and an inverse filter for regions of interest. The arrays also worked for inverse methods other than the one used to design them.
- Tierney TM, Mellor S, O'Neill GC, Holmes N, Boto E, Roberts G, et al. (2020). Pragmatic spatial sampling for wearable MEG arrays. *Scientific Reports*, 10, 21609. DOI: 10.1038/s41598-020-77589-8. <https://doi.org/10.1038/s41598-020-77589-8>
    - **Supports:** diminishing returns from added sensors. Fewer than 100 sensors at about 30 mm spacing gave source discrimination below 1 cm at high SNR, and sensor gain errors hurt deep sources most.

### fNIRS and stimulation montage optimization

- Dmochowski JP, Datta A, Bikson M, Su Y, Parra LC (2011). Optimized multi-electrode stimulation increases focality and intensity at target. *Journal of Neural Engineering*, 8(4), 046011. DOI: 10.1088/1741-2560/8/4/046011. <https://doi.org/10.1088/1741-2560/8/4/046011>
    - **Supports:** forward-model-based montage optimization as an established method in stimulation. The optimal montage depended on the desired field orientation and the current limit.
- Machado A, Cai Z, Pellegrino G, Marcotte O, Vincent T, Lina JM, Kobayashi E, Grova C (2018). Optimal positioning of optodes on the scalp for personalized functional near-infrared spectroscopy investigations. *Journal of Neuroscience Methods*, 309, 91–108. DOI: 10.1016/j.jneumeth.2018.08.006. <https://doi.org/10.1016/j.jneumeth.2018.08.006>
    - **Supports:** fewer sensors scored against a dense reference. Optimal fNIRS montages for target regions gave spatial resolution only slightly below ultra-high-density montages in simulation.
- Saturnino GB, Siebner HR, Thielscher A, Madsen KH (2019). Accessibility of cortical regions to focal TES: dependence on spatial position, safety, and practical constraints. *NeuroImage*, 203, 116183. DOI: 10.1016/j.neuroimage.2019.116183. <https://doi.org/10.1016/j.neuroimage.2019.116183>
    - **Supports:** leadfield-based montage optimization in SimNIBS, with control of the number of active electrodes.
    - **Limits:** deep targets were generally not selectively reachable, a depth limit that parallels the weak tail in amplitude retention (worst 10%).
- Weise K, Madsen KH, Worbs T, Knösche TR, Korshøj A, Thielscher A (2025). A leadfield-free optimization framework for transcranially applied electric currents. *Computers in Biology and Medicine*, 195, 110648. DOI: 10.1016/j.compbiomed.2025.110648. <https://doi.org/10.1016/j.compbiomed.2025.110648>
    - **Supports:** continuous electrode placement on the head surface with overlap prevention, in SimNIBS, for stimulation rather than recording. [Journal version of a bioRxiv preprint that the SimNIBS documentation asks users to cite; see the SimNIBS entry under Software documentation.]

### Sensor selection and optimal-design theory

- Alexanderian A, Petra N, Stadler G, Ghattas O (2014). A-optimal design of experiments for infinite-dimensional Bayesian linear inverse problems with regularized ℓ0-sparsification. *SIAM Journal on Scientific Computing*, 36(5), A2122–A2148. DOI: 10.1137/130933381. <https://doi.org/10.1137/130933381>
    - **Supports:** choosing sensors to minimize posterior uncertainty in a Bayesian linear inverse problem, the same setting as the LMMSE estimator.
- Deb K, Pratap A, Agarwal S, Meyarivan T (2002). A fast and elitist multiobjective genetic algorithm: NSGA-II. *IEEE Transactions on Evolutionary Computation*, 6(2), 182–197. DOI: 10.1109/4235.996017. <https://doi.org/10.1109/4235.996017>
    - **Supports:** Pareto ranking of layouts on several objectives in the result library. [Finding not re-read; topic from the title.]
- Joshi S, Boyd S (2009). Sensor selection via convex optimization. *IEEE Transactions on Signal Processing*, 57(2), 451–462. DOI: 10.1109/TSP.2008.2007095. <https://doi.org/10.1109/TSP.2008.2007095>
    - **Supports:** sensor selection for estimation in a linear model as a formal problem. [Finding not re-read; topic from the title.]
- Krause A, Singh A, Guestrin C (2008). Near-optimal sensor placements in Gaussian processes: theory, efficient algorithms and empirical studies. *Journal of Machine Learning Research*, 9(8), 235–284. No DOI. <https://www.jmlr.org/papers/v9/krause08a.html>
    - **Supports:** choosing sensors that best predict the field at unobserved sites, as field reconstruction retention does. Optimal placement is NP-complete, and a greedy algorithm comes within (1 − 1/e) of the optimum for the mutual-information criterion.
    - **Limits:** the guarantee is for greedy selection of a submodular criterion; it does not transfer to the local radius search.
- Manohar K, Brunton BW, Kutz JN, Brunton SL (2018). Data-driven sparse sensor placement for reconstruction: demonstrating the benefits of exploiting known patterns. *IEEE Control Systems Magazine*, 38(3), 63–86. DOI: 10.1109/MCS.2018.2810460. <https://doi.org/10.1109/MCS.2018.2810460>
    - **Supports:** sensor placement for reconstruction from a basis learned from data, related to the data-derived source prior. [Crossref lists no authors; the authors are taken from Semantic Scholar.]
- Nemhauser GL, Wolsey LA, Fisher ML (1978). An analysis of approximations for maximizing submodular set functions—I. *Mathematical Programming*, 14(1), 265–294. DOI: 10.1007/BF01588971. <https://doi.org/10.1007/BF01588971>
    - **Supports:** the theory behind greedy selection guarantees. [Finding not re-read; topic from the title.]
- Ranieri J, Chebira A, Vetterli M (2014). Near-optimal sensor placement for linear inverse problems. *IEEE Transactions on Signal Processing*, 62(5), 1135–1146. DOI: 10.1109/TSP.2014.2299518. <https://doi.org/10.1109/TSP.2014.2299518>
    - **Supports:** greedy row selection from a forward matrix with a near-optimality guarantee on mean-square error for linear inverse problems.

### Channel selection from recordings

- Alotaiby T, Abd El-Samie FE, Alshebeili SA, Ahmad I (2015). A review of channel selection algorithms for EEG signal processing. *EURASIP Journal on Advances in Signal Processing*, 2015(1), 66. DOI: 10.1186/s13634-015-0251-9. <https://doi.org/10.1186/s13634-015-0251-9>
    - **Supports:** channel subsets from recordings. Channel selection lowers computation, reduces overfitting and shortens setup; the review classifies methods into filter, wrapper, embedded, hybrid and human-based approaches.
- Arvaneh M, Guan C, Ang KK, Quek C (2011). Optimizing the channel selection and classification accuracy in EEG-based BCI. *IEEE Transactions on Biomedical Engineering*, 58(6), 1865–1873. DOI: 10.1109/TBME.2011.2131142. <https://doi.org/10.1109/TBME.2011.2131142>
    - **Supports:** channel subsets from recordings, chosen under a constraint on classification accuracy.
- Baig MZ, Aslam N, Shum HPH (2020). Filtering techniques for channel selection in motor imagery EEG applications: a survey. *Artificial Intelligence Review*, 53(2), 1207–1232. DOI: 10.1007/s10462-019-09694-8. <https://doi.org/10.1007/s10462-019-09694-8>
    - **Supports:** channel subsets from recordings. In most studies reviewed, the same classification performance was reached with 10–30 channels. [Published online in 2019; the issue is dated 2020.]
- Bertrand A (2018). Utility metrics for assessment and subset selection of input variables for linear estimation [Tips & Tricks]. *IEEE Signal Processing Magazine*, 35(6), 93–99. DOI: 10.1109/MSP.2018.2856632. <https://doi.org/10.1109/MSP.2018.2856632>
    - **Supports:** channel subsets from recordings and the LMMSE scoring behind them. The utility of a channel is the increase in linear-estimation error when it is removed; it is nearly free to compute and enables greedy forward or backward selection.
- Lal TN, Schröder M, Hinterberger T, Weston J, Bogdan M, Birbaumer N, Schölkopf B (2004). Support vector channel selection in BCI. *IEEE Transactions on Biomedical Engineering*, 51(6), 1003–1010. DOI: 10.1109/TBME.2004.827827. <https://doi.org/10.1109/TBME.2004.827827>
    - **Supports:** channel subsets from recordings. Channel counts for motor imagery fell substantially without raising error, and the channels selected matched the expected cortical sources.
- Moctezuma LA, Molinas M (2020). EEG channel-selection method for epileptic-seizure classification based on multi-objective optimization. *Frontiers in Neuroscience*, 14, 593. DOI: 10.3389/fnins.2020.00593. <https://doi.org/10.3389/fnins.2020.00593>
    - **Supports:** Pareto-based channel selection, maximizing classification accuracy while minimizing channel count.
- Montoya-Martínez J, Vanthornhout J, Bertrand A, Francart T (2021). Effect of number and placement of EEG electrodes on measurement of neural tracking of speech. *PLoS ONE*, 16(2), e0246769. DOI: 10.1371/journal.pone.0246769. <https://doi.org/10.1371/journal.pone.0246769>
    - **Supports:** asking which limited electrode set to use. On 64-channel data from 90 subjects, subject-independent decoding stayed stable from 64 down to 22 channels.
- Mundanad Narayanan A, Zink R, Bertrand A (2021). EEG miniaturization limits for stimulus decoding with EEG sensor networks. *Journal of Neural Engineering*, 18(5), 056042. DOI: 10.1088/1741-2552/ac2629. <https://doi.org/10.1088/1741-2552/ac2629>
    - **Supports:** emulating small devices from dense recordings.
    - **Limits:** decoding stayed roughly stable down to 3 cm between electrodes and then dropped quickly, even at optimized locations.
- Narayanan AM, Bertrand A (2020). Analysis of miniaturization effects and channel selection strategies for EEG sensor networks with application to auditory attention detection. *IEEE Transactions on Biomedical Engineering*, 67(1), 234–244. DOI: 10.1109/TBME.2019.2911728. <https://doi.org/10.1109/TBME.2019.2911728>
    - **Supports:** placement over count for small devices. With optimally selected node positions, short-distance measurements matched an equal number of long-distance ones.
- Schirrmeister RT, Springenberg JT, Fiederer LDJ, Glasstetter M, Eggensperger K, Tangermann M, et al. (2017). Deep learning with convolutional neural networks for EEG decoding and visualization. *Human Brain Mapping*, 38(11), 5391–5420. DOI: 10.1002/hbm.23730. <https://doi.org/10.1002/hbm.23730>
    - **Supports:** the source of the High-Gamma Dataset, used to validate the data-derived source prior and channel subsets from recordings.
- Xia H, Ruan D, Cohen MS (2014). Removing ballistocardiogram (BCG) artifact from full-scalp EEG acquired inside the MR scanner with Orthogonal Matching Pursuit (OMP). *Frontiers in Neuroscience*, 8, 218. DOI: 10.3389/fnins.2014.00218. <https://doi.org/10.3389/fnins.2014.00218>
    - **Supports:** inferring a full-scalp field from a channel subset. A subset of 20 of 256 channels was enough to infer the full-scalp artefact. [Article number taken from the DOI suffix.]

## Head models and forward computation

These works describe how EEG lead fields are computed with the finite element method, and the SimNIBS pipeline that builds the Ernie head model and the other head models.

### Forward computation and reciprocity

- Hallez H, Vanrumste B, Grech R, Muscat J, De Clercq W, Vergult A, et al. (2007). Review on solving the forward problem in EEG source analysis. *Journal of NeuroEngineering and Rehabilitation*, 4, 46. DOI: 10.1186/1743-0003-4-46. <https://doi.org/10.1186/1743-0003-4-46>
    - **Supports:** computing lead fields per electrode through reciprocity, which makes forward calculations faster. The review compares boundary, finite element and finite difference methods.
    - **Limits:** it notes that measuring and validating conductivities in vivo remains an important open topic.
- Pursiainen S, Lucka F, Wolters CH (2012). Complete electrode model in EEG: relationship and differences to the point electrode model. *Physics in Medicine and Biology*, 57(4), 999–1017. DOI: 10.1088/0031-9155/57/4/999. <https://doi.org/10.1088/0031-9155/57/4/999>
    - **Limits:** the point electrode model is the limit of the complete electrode model as contact impedance goes to infinity and electrode size to zero; forward and inverse errors depend on impedance and size. Point electrodes are an approximation.
- Rush S, Driscoll DA (1969). EEG electrode sensitivity—an application of reciprocity. *IEEE Transactions on Biomedical Engineering*, BME-16(1), 15–22. DOI: 10.1109/TBME.1969.4502598. <https://doi.org/10.1109/TBME.1969.4502598>
    - **Supports:** the reciprocity principle behind per-electrode lead fields. [Not read in full; its use is described by Hallez et al. 2007 and Wagner et al. 2016.]
- Vorwerk J, Cho JH, Rampp S, Hamer H, Knösche TR, Wolters CH (2014). A guideline for head volume conductor modeling in EEG and MEG. *NeuroImage*, 100, 590–607. DOI: 10.1016/j.neuroimage.2014.06.040. <https://doi.org/10.1016/j.neuroimage.2014.06.040>
    - **Supports:** the tissue classes in the head model. Including CSF and separating gray and white matter matter most; omitting white-matter anisotropy is called admissible.
- Wagner S, Lucka F, Vorwerk J, Herrmann CS, Nolte G, Burger M, Wolters CH (2016). Using reciprocity for relating the simulation of transcranial current stimulation to the EEG forward problem. *NeuroImage*, 140, 163–173. DOI: 10.1016/j.neuroimage.2016.04.005. <https://doi.org/10.1016/j.neuroimage.2016.04.005>
    - **Supports:** computing EEG lead fields with a stimulation solver. The reciprocal approach is algebraically identical to the direct approach for general head models.
    - **Limits:** the element type changed simulated current-flow orientation by up to 45°.
- Weinstein D, Zhukov L, Johnson C (2000). Lead-field bases for electroencephalography source imaging. *Annals of Biomedical Engineering*, 28(9), 1059–1065. DOI: 10.1114/1.1310220. <https://doi.org/10.1114/1.1310220>
    - **Supports:** precomputing lead-field bases in a realistic head. It names the lack of efficient realistic lead-field computation as a main reason realistic models lagged behind spherical ones.
- Wolters CH, Anwander A, Tricoche X, Weinstein D, Koch MA, MacLeod RS (2006). Influence of tissue conductivity anisotropy on EEG/MEG field and return current computation in a realistic head model: a simulation and visualization study using high-resolution finite element modeling. *NeuroImage*, 30(3), 813–826. DOI: 10.1016/j.neuroimage.2005.10.014. <https://doi.org/10.1016/j.neuroimage.2005.10.014>
    - **Limits:** skull and white-matter anisotropy substantially affect the EEG forward computation, more so for deeper sources. The head models here are isotropic.

### SimNIBS, segmentation and cortical regions

- Desikan RS, Ségonne F, Fischl B, Quinn BT, Dickerson BC, Blacker D, et al. (2006). An automated labeling system for subdividing the human cerebral cortex on MRI scans into gyral based regions of interest. *NeuroImage*, 31(3), 968–980. DOI: 10.1016/j.neuroimage.2006.01.021. <https://doi.org/10.1016/j.neuroimage.2006.01.021>
    - **Supports:** the cortical atlas regions used to define source regions of interest.
- Huang Y, Liu AA, Lafon B, Friedman D, Dayan M, Wang X, et al. (2017). Measurements and models of electric fields in the in vivo human brain during transcranial electric stimulation. *eLife*, 6, e18834. DOI: 10.7554/eLife.18834. <https://doi.org/10.7554/eLife.18834>
    - **Supports:** background on validating head-model field calculations against intracranial measurements. [Finding not re-read; topic from the title.]
- Lanfer B, Scherg M, Dannhauer M, Knösche TR, Burger M, Wolters CH (2012). Influences of skull segmentation inaccuracies on EEG source analysis. *NeuroImage*, 62(1), 418–431. DOI: 10.1016/j.neuroimage.2012.05.006. <https://doi.org/10.1016/j.neuroimage.2012.05.006>
    - **Limits:** large skull errors close to the source space, such as cutting the model just below the skull, caused errors of 20 mm or more; local defects mattered only near the defect.
- Nielsen JD, Madsen KH, Puonti O, Siebner HR, Bauer C, Madsen CG, Saturnino GB, Thielscher A (2018). Automatic skull segmentation from MR images for realistic volume conductor models of the head: assessment of the state-of-the-art. *NeuroImage*, 174, 587–598. DOI: 10.1016/j.neuroimage.2018.03.001. <https://doi.org/10.1016/j.neuroimage.2018.03.001>
    - **Supports:** background on skull segmentation for head models. [Finding not re-read; topic from the title.]
- Nielsen JD, Puonti O, Xue R, Thielscher A, Madsen KH (2023). Evaluating the influence of anatomical accuracy and electrode positions on EEG forward solutions. *NeuroImage*, 277, 120259. DOI: 10.1016/j.neuroimage.2023.120259. <https://doi.org/10.1016/j.neuroimage.2023.120259>
    - **Supports:** the SimNIBS EEG forward model used for the Ernie head model and the other head models. It evaluates how anatomical accuracy and electrode positions affect EEG forward solutions.
- Puonti O, Saturnino GB, Madsen KH, Thielscher A (2020). Value and limitations of intracranial recordings for validating electric field modeling for transcranial brain stimulation. *NeuroImage*, 208, 116431. DOI: 10.1016/j.neuroimage.2019.116431. <https://doi.org/10.1016/j.neuroimage.2019.116431>
    - **Supports:** background on how field models are validated. [Finding not re-read; topic from the title.]
- Puonti O, Van Leemput K, Saturnino GB, Siebner HR, Madsen KH, Thielscher A (2020). Accurate and robust whole-head segmentation from magnetic resonance images for individualized head modeling. *NeuroImage*, 219, 117044. DOI: 10.1016/j.neuroimage.2020.117044. <https://doi.org/10.1016/j.neuroimage.2020.117044>
    - **Supports:** the SimNIBS segmentation behind the head models. It segments 15 tissues and adapts to scanner and sequence differences.
    - **Limits:** unaccounted MR artefacts can still cause local differences of up to 30 % of the peak field.
- Saturnino GB, Madsen KH, Thielscher A (2019). Electric field simulations for transcranial brain stimulation using FEM: an efficient implementation and error analysis. *Journal of Neural Engineering*, 16(6), 066032. DOI: 10.1088/1741-2552/ab41ba. <https://doi.org/10.1088/1741-2552/ab41ba>
    - **Supports:** the finite element solver in SimNIBS used to compute the lead fields.
- Saturnino GB, Puonti O, Nielsen JD, Antonenko D, Madsen KH, Thielscher A (2019). SimNIBS 2.1: a comprehensive pipeline for individualized electric field modelling for transcranial brain stimulation. In: Makarov S, Horner M, Noetscher G (eds.), *Brain and Human Body Modeling: Computational Human Modeling at EMBC 2018*, pp. 3–25. Cham: Springer International Publishing. ISBN 978-3-030-21292-6. DOI: 10.1007/978-3-030-21293-3_1. <https://doi.org/10.1007/978-3-030-21293-3_1>
    - **Supports:** the SimNIBS pipeline from head meshing to field calculation. [Finding not re-read; topic from the title.]
- Thielscher A, Antunes A, Saturnino GB (2015). Field modeling for transcranial magnetic stimulation: a useful tool to understand the physiological effects of TMS? In: *2015 37th Annual International Conference of the IEEE Engineering in Medicine and Biology Society (EMBC)*, pp. 222–225. IEEE. DOI: 10.1109/EMBC.2015.7318340. <https://doi.org/10.1109/EMBC.2015.7318340>
    - **Supports:** the SimNIBS pipeline for finite element simulations.
    - **Limits:** it names model uncertainty as the first of three open challenges for field modelling.
- Windhoff M, Opitz A, Thielscher A (2013). Electric field calculations in brain stimulation based on finite elements: an optimized processing pipeline for the generation and usage of accurate individual head models. *Human Brain Mapping*, 34(4), 923–935. DOI: 10.1002/hbm.21479. <https://doi.org/10.1002/hbm.21479>
    - **Supports:** background on the SimNIBS pipeline for individual head models. [Finding not re-read; topic from the title. Published online in 2011; the issue is dated 2013.]

## Head-model and conductivity uncertainty

These works show that conductivity and anatomy change source estimates. They support the conductivity scenarios (skull ×0.5 and ×2), the heads studies with other head models, and reporting rankings relative to standard64 rather than absolute errors.

### Conductivity

- Antonakakis M, Schrader S, Aydin Ü, Khan A, Gross J, Zervakis M, Rampp S, Wolters CH (2020). Inter-subject variability of skull conductivity and thickness in calibrated realistic head models. *NeuroImage*, 223, 117353. DOI: 10.1016/j.neuroimage.2020.117353. <https://doi.org/10.1016/j.neuroimage.2020.117353>
    - **Supports:** the skull ×0.5 and ×2 conductivity scenarios. Individually calibrated skull conductivity across 20 adults was 8.44 ± 4.84 mS/m and fell with age.
- McCann H, Pisano G, Beltrachini L (2019). Variation in reported human head tissue electrical conductivity values. *Brain Topography*, 32(5), 825–858. DOI: 10.1007/s10548-019-00710-2. <https://doi.org/10.1007/s10548-019-00710-2>
    - **Supports:** the conductivity scenarios. A meta-analysis of 56 papers found that variation in skull and other conductivities is significantly explained by method and demographics; the recommended weighted mean for the whole skull is 0.02 S/m.
- Rimpiläinen V, Koulouri A, Lucka F, Kaipio JP, Wolters CH (2019). Improved EEG source localization with Bayesian uncertainty modelling of unknown skull conductivity. *NeuroImage*, 188, 252–260. DOI: 10.1016/j.neuroimage.2018.11.058. <https://doi.org/10.1016/j.neuroimage.2018.11.058>
    - **Supports:** background on modelling unknown skull conductivity. [Finding not re-read; topic from the title.]
- Saturnino GB, Thielscher A, Madsen KH, Knösche TR, Weise K (2019). A principled approach to conductivity uncertainty analysis in electric field calculations. *NeuroImage*, 188, 821–834. DOI: 10.1016/j.neuroimage.2018.12.053. <https://doi.org/10.1016/j.neuroimage.2018.12.053>
    - **Supports:** conductivity scenarios in SimNIBS. For stimulation fields, conductivity uncertainty affected magnitude much more than direction and spatial distribution.
- Stenroos M, Hauk O (2013). Minimum-norm cortical source estimation in layered head models is robust against skull conductivity error. *NeuroImage*, 81, 265–272. DOI: 10.1016/j.neuroimage.2013.04.086. <https://doi.org/10.1016/j.neuroimage.2013.04.086>
    - **Supports:** minimum-norm-type estimators under skull conductivity error. Skull conductivity changed lead-field amplitudes moderately but their shapes little, and localization by minimum-norm estimates was only minimally affected.
    - **Limits:** results for dipole fitting do not carry over to other estimators.
- Vallaghé S, Clerc M (2009). A global sensitivity analysis of three- and four-layer EEG conductivity models. *IEEE Transactions on Biomedical Engineering*, 56(4), 988–995. DOI: 10.1109/TBME.2008.2009315. <https://doi.org/10.1109/TBME.2008.2009315>
    - **Supports:** background on the sensitivity of EEG to layer conductivities. [Finding not re-read; topic from the title.]
- Vorwerk J, Aydin Ü, Wolters CH, Butson CR (2019). Influence of head tissue conductivity uncertainties on EEG dipole reconstruction. *Frontiers in Neuroscience*, 13, 531. DOI: 10.3389/fnins.2019.00531. <https://doi.org/10.3389/fnins.2019.00531>
    - **Supports:** the skull conductivity scenarios. Skin and skull conductivity uncertainty moved source localization by several centimetres; CSF uncertainty was negligible.
- Vorwerk J, Wolters CH, Baumgarten D (2024). Global sensitivity of EEG source analysis to tissue conductivity uncertainties. *Frontiers in Human Neuroscience*, 18, 1335212. DOI: 10.3389/fnhum.2024.1335212. <https://doi.org/10.3389/fnhum.2024.1335212>
    - **Limits:** in a whole-cortex study, tangential sulcal sources were the most sensitive to conductivity. Fixed normal orientations do not remove this sensitivity.

### Template and individual heads

- Akalin Acar Z, Makeig S (2013). Effects of forward model errors on EEG source localization. *Brain Topography*, 26(3), 378–396. DOI: 10.1007/s10548-012-0274-6. <https://doi.org/10.1007/s10548-012-0274-6>
    - **Supports:** reporting absolute errors for one head model as optimistic. Templates warped to measured electrode positions gave median dipole errors of 4.1–6.2 mm, and basal sources reached about 20 mm.
    - **Limits:** raising the brain-to-skull conductivity ratio from 25:1 to 80:1 moved dipoles outward by 12.4 mm (median).
- Depuydt E, Criel Y, De Letter M, van Mierlo P (2024). Investigating the effect of template head models on event-related potential source localization: a simulation and real-data study. *Frontiers in Neuroscience*, 18, 1443752. DOI: 10.3389/fnins.2024.1443752. <https://doi.org/10.3389/fnins.2024.1443752>
    - **Limits:** template head models captured simulated ERP sources less accurately, with more spurious and fewer true sources.
- Huang Y, Parra LC, Haufe S (2016). The New York Head—a precise standardized volume conductor model for EEG source localization and tES targeting. *NeuroImage*, 140, 150–162. DOI: 10.1016/j.neuroimage.2015.12.019. <https://doi.org/10.1016/j.neuroimage.2015.12.019>
    - **Supports:** checking results on other head models. An averaged template outperformed finite element models of mismatched individual anatomies, judged against four individual models.
    - **Limits:** a single individual head, such as Ernie, is not a neutral stand-in for other people.
- Liu C, Downey RJ, Mu Y, Richer N, Hwang J, Shah VA, et al. (2023). Comparison of EEG source localization using simplified and anatomically accurate head models in younger and older adults. *IEEE Transactions on Neural Systems and Rehabilitation Engineering*, 31, 2591–2602. DOI: 10.1109/TNSRE.2023.3281356. <https://doi.org/10.1109/TNSRE.2023.3281356>
    - **Supports:** recording electrode positions. Co-registering digitized positions to a generic model reduced its discrepancies by about 6 mm.
    - **Limits:** generic head models produced source discrepancies of up to 2 cm against individual models.
- Valdés-Hernández PA, von Ellenrieder N, Ojeda-Gonzalez A, Kochen S, Alemán-Gómez Y, Muravchik C, Valdés-Sosa PA (2009). Approximate average head models for EEG source imaging. *Journal of Neuroscience Methods*, 185(1), 125–132. DOI: 10.1016/j.jneumeth.2009.09.005. <https://doi.org/10.1016/j.jneumeth.2009.09.005>
    - **Supports:** the heads studies. Across 305 subjects, imperfect anatomical correspondence between cortices was the most important cause of localization error, and average models outperformed a random individual model.
    - **Limits:** lead fields of approximate models should not constrain sources to be normal to the cortex, whereas the source model here uses fixed normal orientations.
- von Ellenrieder N, Muravchik CH, Nehorai A (2006). Effects of geometric head model perturbations on the EEG forward and inverse problems. *IEEE Transactions on Biomedical Engineering*, 53(3), 421–429. DOI: 10.1109/TBME.2005.869769. <https://doi.org/10.1109/TBME.2005.869769>
    - **Supports:** background on geometric head-model errors. [Finding not re-read; topic from the title.]

## Electrode positions, placement error and contact noise

These works support the cross-session robustness checks (electrode dropout, unequal contact noise and cap re-placement), the grid-displacement study, and coordinate import with MNI coordinates and 10-05 names.

### Placement error

- Atcherson SR, Gould HJ, Pousson MA, Prout TM (2007). Variability of electrode positions using electrode caps. *Brain Topography*, 20(2), 105–111. DOI: 10.1007/s10548-007-0036-z. <https://doi.org/10.1007/s10548-007-0036-z>
    - **Supports:** the displacement size in cap re-placement. A cap placed on 10 adults on three occasions gave electrode-position standard deviations of 3.0–12.7 mm.
- Beltrachini L, von Ellenrieder N, Muravchik CH (2011). General bounds for electrode mislocation on the EEG inverse problem. *Computer Methods and Programs in Biomedicine*, 103(1), 1–9. DOI: 10.1016/j.cmpb.2010.05.008. <https://doi.org/10.1016/j.cmpb.2010.05.008>
    - **Supports:** bounding the effect of position error independently of the inverse method. With 120 electrodes and 5 mm position error, the lower bound on source-depth standard deviation was about 1 mm in the worst case.
- Clausner T, Dalal SS, Crespo-García M (2017). Photogrammetry-based head digitization for rapid and accurate localization of EEG electrodes and MEG fiducial markers using a single digital SLR camera. *Frontiers in Neuroscience*, 11, 264. DOI: 10.3389/fnins.2017.00264. <https://doi.org/10.3389/fnins.2017.00264>
    - **Supports:** background on digitizing electrode positions, the redigitized case of cap re-placement. [Finding not re-read; topic from the title.]
- Dalal SS, Rampp S, Willomitzer F, Ettl S (2014). Consequences of EEG electrode position error on ultimate beamformer source reconstruction performance. *Frontiers in Neuroscience*, 8, 42. DOI: 10.3389/fnins.2014.00042. <https://doi.org/10.3389/fnins.2014.00042>
    - **Supports:** the redigitized case of cap re-placement. An electromagnetic digitizer had 6.8 mm mean error against 1.5 mm for an optical sensor.
    - **Limits:** digitizer-based positions degraded beamformer output SNR by up to several dB, enough to decide whether deep sources are detected.
- Homölle S, Oostenveld R (2019). Using a structured-light 3D scanner to improve EEG source modeling with more accurate electrode positions. *Journal of Neuroscience Methods*, 326, 108378. DOI: 10.1016/j.jneumeth.2019.108378. <https://doi.org/10.1016/j.jneumeth.2019.108378>
    - **Supports:** background on digitizing electrode positions. [Finding not re-read; topic from the title.]
- Khosla D, Don M, Kwong B (1999). Spatial mislocalization of EEG electrodes – effects on accuracy of dipole estimation. *Clinical Neurophysiology*, 110(2), 261–271. DOI: 10.1016/S0013-4694(98)00121-7. <https://doi.org/10.1016/S0013-4694(98)00121-7>
    - **Supports:** the grid-displacement study and cap re-placement. Digitized positions deviated on average about 4° from standard 10-20 positions, which moved dipoles by about 8 mm, within the range of other modelling and noise errors.
- Scrivener CL, Reader AT (2022). Variability of EEG electrode positions and their underlying brain regions: visualizing gel artifacts from a simultaneous EEG-fMRI dataset. *Brain and Behavior*, 12(2), e2476. DOI: 10.1002/brb3.2476. <https://doi.org/10.1002/brb3.2476>
    - **Supports:** the displacement size in cap re-placement. For a fixed cap in 20 participants, mean position standard deviations were 3.94, 5.55 and 7.17 mm along the three MNI axes.
    - **Limits:** the cortical region under a given electrode was not consistent across participants.
- Shirazi SY, Huang HJ (2019). More reliable EEG electrode digitizing methods can reduce source estimation uncertainty, but current methods already accurately identify Brodmann areas. *Frontiers in Neuroscience*, 13, 1159. DOI: 10.3389/fnins.2019.01159. <https://doi.org/10.3389/fnins.2019.01159>
    - **Supports:** digitizing positions instead of using a template. Position variability of about 1 cm could shift a fitted source by up to 2 cm, and template positions reduced Brodmann-area accuracy from over 80 % to about 50 %.
- Taberna GA, Marino M, Ganzetti M, Mantini D (2019). Spatial localization of EEG electrodes using 3D scanning. *Journal of Neural Engineering*, 16(2), 026020. DOI: 10.1088/1741-2552/aafdd1. <https://doi.org/10.1088/1741-2552/aafdd1>
    - **Supports:** the redigitized case of cap re-placement. 3D scanning gave median co-registration error below 3.0 mm, more precise than electromagnetic digitization.
- Wang Y, Gotman J (2001). The influence of electrode location errors on EEG dipole source localization with a realistic head model. *Clinical Neurophysiology*, 112(9), 1777–1780. DOI: 10.1016/S1388-2457(01)00594-6. <https://doi.org/10.1016/S1388-2457(01)00594-6>
    - **Supports:** the grid-displacement study. Mean 5 mm displacements caused about 5 mm localization error without noise and about 2 mm with realistic noise, which the authors judge negligible compared with noise.

### Standard positions and MNI registration

- Jurcak V, Tsuzuki D, Dan I (2007). 10/20, 10/10, and 10/5 systems revisited: their validity as relative head-surface-based positioning systems. *NeuroImage*, 34(4), 1600–1611. DOI: 10.1016/j.neuroimage.2006.09.024. <https://doi.org/10.1016/j.neuroimage.2006.09.024>
    - **Supports:** coordinate import with 10-05 names and MNI coordinates. Virtual 10/10 and 10/5 positions from 17 heads were normalized to MNI space; 241 of the 329 10/5 positions could be set without neighbours overlapping.
- Okamoto M, Dan H, Sakamoto K, Takeo K, Shimizu K, Kohno S, et al. (2004). Three-dimensional probabilistic anatomical cranio-cerebral correlation via the international 10–20 system oriented for transcranial functional brain mapping. *NeuroImage*, 21(1), 99–111. DOI: 10.1016/j.neuroimage.2003.08.026. <https://doi.org/10.1016/j.neuroimage.2003.08.026>
    - **Supports:** background on relating 10-20 positions to brain anatomy. [Finding not re-read; topic from the title.]
- Oostenveld R, Praamstra P (2001). The five percent electrode system for high-resolution EEG and ERP measurements. *Clinical Neurophysiology*, 112(4), 713–719. DOI: 10.1016/S1388-2457(00)00527-7. <https://doi.org/10.1016/S1388-2457(00)00527-7>
    - **Supports:** 10-05 electrode names. It defines the 10-5 system with 345 named locations.
- Singh AK, Okamoto M, Dan H, Jurcak V, Dan I (2005). Spatial registration of multichannel multi-subject fNIRS data to MNI space without MRI. *NeuroImage*, 27(4), 842–851. DOI: 10.1016/j.neuroimage.2005.05.019. <https://doi.org/10.1016/j.neuroimage.2005.05.019>
    - **Supports:** importing MNI coordinates. Registering head-surface points to reference MRIs gave probabilistic MNI registration with a standard deviation of about 4.7–7.0 mm, which bounds the precision of such imports.

### Contact impedance, noise and bad channels

- Bigdely-Shamlo N, Mullen T, Kothe C, Su KM, Robbins KA (2015). The PREP pipeline: standardized preprocessing for large-scale EEG analysis. *Frontiers in Neuroinformatics*, 9, 16. DOI: 10.3389/fninf.2015.00016. <https://doi.org/10.3389/fninf.2015.00016>
    - **Supports:** re-referencing after electrode dropout. Noisy channels contaminate the average reference, and detecting them depends on the reference.
    - **Limits:** the abstract gives no rate of bad channels.
- Ferree TC, Luu P, Russell GS, Tucker DM (2001). Scalp electrode impedance, infection risk, and EEG data quality. *Clinical Neurophysiology*, 112(3), 536–544. DOI: 10.1016/S1388-2457(00)00533-2. <https://doi.org/10.1016/S1388-2457(00)00533-2>
    - **Limits:** with high-input-impedance amplifiers, raising impedance from under 10 kΩ to 40 kΩ caused no significant amplitude change in any EEG band. Unequal contact noise depends on the amplifier.
- Kappenman ES, Luck SJ (2010). The effects of electrode impedance on data quality and statistical significance in ERP recordings. *Psychophysiology*, 47(5), 888–904. DOI: 10.1111/j.1469-8986.2010.01009.x. <https://doi.org/10.1111/j.1469-8986.2010.01009.x>
    - **Supports:** unequal contact noise. High-impedance sites showed more low-frequency noise, especially in warm, humid conditions, which increased the trials needed for significance. [Volume and pages from PubMed; Crossref gives none.]
- Mathewson KE, Harrison TJL, Kizuk SAD (2017). High and dry? Comparing active dry EEG electrodes to active and passive wet electrodes. *Psychophysiology*, 54(1), 74–82. DOI: 10.1111/psyp.12536. <https://doi.org/10.1111/psyp.12536>
    - **Supports:** unequal contact noise for dry electrodes. Active dry electrodes with very high impedance showed more noise and lower statistical power, while active wet electrodes were insensitive to moderate impedance. [Published online in 2016; the issue is dated 2017.]

## Source-estimation resolution and localization metrics

These works relate to the relative localization score and amplitude retention (worst 10%), and to the choice of reporting localization separately from field reconstruction.

- Grech R, Cassar T, Muscat J, Camilleri KP, Fabri SG, Zervakis M, et al. (2008). Review on solving the inverse problem in EEG source analysis. *Journal of NeuroEngineering and Rehabilitation*, 5, 25. DOI: 10.1186/1743-0003-5-25. <https://doi.org/10.1186/1743-0003-5-25>
    - **Supports:** background on inverse methods. In the authors' comparison, regularized sLORETA gave the best single-source localization among the linear methods tested.
- Hauk O, Wakeman DG, Henson R (2011). Comparison of noise-normalized minimum norm estimates for MEG analysis using multiple resolution metrics. *NeuroImage*, 54(3), 1966–1974. DOI: 10.1016/j.neuroimage.2010.09.053. <https://doi.org/10.1016/j.neuroimage.2010.09.053>
    - **Supports:** using several resolution metrics.
    - **Limits:** low localization error helps for single sources, but its benefit for complex source distributions is not obvious.
- Hauk O, Stenroos M, Treder MS (2022). Towards an objective evaluation of EEG/MEG source estimation methods – the linear approach. *NeuroImage*, 255, 119177. DOI: 10.1016/j.neuroimage.2022.119177. <https://doi.org/10.1016/j.neuroimage.2022.119177>
    - **Supports:** evaluating linear estimators through the resolution matrix, with point-spread and cross-talk functions, peak localization error and spatial deviation.
    - **Limits:** spatial deviation and cross-talk were far less favourable than peak error for all methods, especially for deep areas. Peak error alone is incomplete.
- Liu AK, Dale AM, Belliveau JW (2002). Monte Carlo simulation studies of EEG and MEG localization accuracy. *Human Brain Mapping*, 16(1), 47–62. DOI: 10.1002/hbm.10024. <https://doi.org/10.1002/hbm.10024>
    - **Supports:** comparing arrays by simulated localization with a distributed linear inverse, with forward-model error removed by design, as the relative localization score does under the nominal model.
- Molins A, Stufflebeam SM, Brown EN, Hämäläinen MS (2008). Quantification of the benefit from integrating MEG and EEG data in minimum ℓ2-norm estimation. *NeuroImage*, 42(3), 1069–1077. DOI: 10.1016/j.neuroimage.2008.05.064. <https://doi.org/10.1016/j.neuroimage.2008.05.064>
    - **Supports:** scoring sensor configurations with forward-model rank and resolution metrics, the closest published relative of field reconstruction retention. Adding EEG to MEG raised effective rank and lowered spread, most strongly for deep areas.
- Samuelsson JG, Peled N, Mamashli F, Ahveninen J, Hämäläinen MS (2021). Spatial fidelity of MEG/EEG source estimates: a general evaluation approach. *NeuroImage*, 224, 117430. DOI: 10.1016/j.neuroimage.2020.117430. <https://doi.org/10.1016/j.neuroimage.2020.117430>
    - **Supports:** fixing the nominal SNR when comparing layouts. Spatial fidelity varied strongly with SNR along a largely sigmoidal curve.
- Unnwongse K, Rampp S, Wehner T, Kowoll A, Parpaley Y, von Lehe M, et al. (2023). Validating EEG source imaging using intracranial electrical stimulation. *Brain Communications*, 5(1), fcad023. DOI: 10.1093/braincomms/fcad023. <https://doi.org/10.1093/braincomms/fcad023>
    - **Supports:** treating deep sources as the hard tail, which amplitude retention (worst 10%) targets. 3619 known intracranial sources were localized from 37-channel EEG with individual finite element models.
    - **Limits:** mean errors were 10.3–26 mm and grew with depth and with lower skull conductivity, so absolute errors from one model are optimistic. [Crossref dates the article 29 December 2022; the volume is dated 2023.]

## ECG and EOG interference

These works describe the cardiac and ocular fields that signal simulation adds: ECG as a low-order polynomial field and EOG as two Gaussian lobes with a blink waveform.

- Arnau S, Sharifian F, Wascher E, Larra MF (2023). Removing the cardiac field artifact from the EEG using neural network regression. *Psychophysiology*, 60(10), e14323. DOI: 10.1111/psyp.14323. <https://doi.org/10.1111/psyp.14323>
    - **Supports:** including ECG in signal simulation. Scalp electrodes capture the heart's field, a heavy contaminant when EEG is analysed time-locked to cardiac events.
- Berg P, Scherg M (1991). Dipole models of eye movements and blinks. *Electroencephalography and Clinical Neurophysiology*, 79(1), 36–44. DOI: 10.1016/0013-4694(91)90154-V. <https://doi.org/10.1016/0013-4694(91)90154-V>
    - **Limits:** each type of eye activity needed equivalent dipoles with different locations and orientations, so one fixed EOG map is a simplification.
- Croft RJ, Barry RJ (2000). Removal of ocular artifact from the EEG: a review. *Neurophysiologie Clinique / Clinical Neurophysiology*, 30(1), 5–19. DOI: 10.1016/S0987-7053(00)00055-1. <https://doi.org/10.1016/S0987-7053(00)00055-1>
    - **Supports:** background on EOG correction, including how many EOG channels are needed and how to treat different eye movements.
- Dimigen O (2020). Optimizing the ICA-based removal of ocular EEG artifacts from free viewing experiments. *NeuroImage*, 207, 116117. DOI: 10.1016/j.neuroimage.2019.116117. <https://doi.org/10.1016/j.neuroimage.2019.116117>
    - **Supports:** background on removing ocular artefacts. With common settings ICA left residual artefacts; optimized training removed virtually all of them.
- Dirlich G, Vogl L, Plaschke M, Strian F (1997). Cardiac field effects on the EEG. *Electroencephalography and Clinical Neurophysiology*, 102(4), 307–315. DOI: 10.1016/S0013-4694(96)96506-2. <https://doi.org/10.1016/S0013-4694(96)96506-2>
    - **Supports:** a spatially smooth ECG field on the scalp.
    - **Limits:** the cardiac field was most prominent during the QRS complex and the T wave, distinctly asymmetric between the hemispheres, and changed with head turning. One fixed polynomial map is a simplification.
- Harmening N, Klug M, Gramann K, Miklody D (2022). HArtMuT—modeling eye and muscle contributors in neuroelectric imaging. *Journal of Neural Engineering*, 19(6), 066041. DOI: 10.1088/1741-2552/aca8ce. <https://doi.org/10.1088/1741-2552/aca8ce>
    - **Supports:** forward-modelling non-brain sources, the closest published precedent for the EOG simulation. It extends a head model to the neck with eye and muscle sources.
    - **Limits:** it covers eye and muscle sources, not cardiac ones.
- Lins OG, Picton TW, Berg P, Scherg M (1993). Ocular artifacts in EEG and event-related potentials I: scalp topography. *Brain Topography*, 6(1), 51–63. DOI: 10.1007/BF01234127. <https://doi.org/10.1007/BF01234127>
    - **Supports:** the EOG field. Ocular artefacts come from the corneo-retinal potential, and their scalp distribution follows location-dependent propagation factors.
    - **Limits:** the factors differ significantly between blinks and upward eye movements.
- Plöchl M, Ossandón JP, König P (2012). Combining EEG and eye tracking: identification, characterization, and correction of eye movement artifacts in electroencephalographic data. *Frontiers in Human Neuroscience*, 6, 278. DOI: 10.3389/fnhum.2012.00278. <https://doi.org/10.3389/fnhum.2012.00278>
    - **Limits:** corneo-retinal, saccadic spike and eyelid artefacts arise from different independent sources, and their contributions depend on electrode site, gaze direction and reference.
- Tamburro G, Stone DB, Comani S (2019). Automatic removal of cardiac interference (ARCI): a new approach for EEG data. *Frontiers in Neuroscience*, 13, 441. DOI: 10.3389/fnins.2019.00441. <https://doi.org/10.3389/fnins.2019.00441>
    - **Supports:** including cardiac interference in signal simulation, in 64- to 128-channel wet and dry caps.
    - **Limits:** cardiac interference also has pulse-related components that an electrical field model does not represent.
- Urigüen JA, Garcia-Zapirain B (2015). EEG artifact removal—state-of-the-art and guidelines. *Journal of Neural Engineering*, 12(3), 031001. DOI: 10.1088/1741-2560/12/3/031001. <https://doi.org/10.1088/1741-2560/12/3/031001>
    - **Supports:** background on ocular, muscular and cardiac artefacts and their removal.

## Related software

These tools analyse recorded data, compute forward models, simulate EEG, or design arrays in other modalities. None of their reference publications describes searching for EEG layouts, scoring a layout against a reference layout, or restricting a layout to a scalp region. They are dependencies, interoperability targets and analogues.

### EEG and MEG toolboxes

- Delorme A, Makeig S (2004). EEGLAB: an open source toolbox for analysis of single-trial EEG dynamics including independent component analysis. *Journal of Neuroscience Methods*, 134(1), 9–21. DOI: 10.1016/j.jneumeth.2003.10.009. <https://doi.org/10.1016/j.jneumeth.2003.10.009>
    - **Supports:** the EEGLAB `.sfp` export. EEGLAB analyses recorded data and does not design layouts.
- Gramfort A, Luessi M, Larson E, Engemann DA, Strohmeier D, Brodbeck C, et al. (2013). MEG and EEG data analysis with MNE-Python. *Frontiers in Neuroscience*, 7, 267. DOI: 10.3389/fnins.2013.00267. <https://doi.org/10.3389/fnins.2013.00267>
    - **Supports:** the MNE-Python `.elc` export. MNE-Python provides standard montages but no layout design. [Crossref lists only the first author; the author list is from Europe PMC, PMID 24431986.]
- Gramfort A, Luessi M, Larson E, Engemann DA, Strohmeier D, Brodbeck C, Parkkonen L, Hämäläinen MS (2014). MNE software for processing MEG and EEG data. *NeuroImage*, 86, 446–460. DOI: 10.1016/j.neuroimage.2013.10.027. <https://doi.org/10.1016/j.neuroimage.2013.10.027>
    - **Supports:** the MNE-Python `.elc` export. It describes the MNE suite, including forward and inverse modelling.
- Oostenveld R, Fries P, Maris E, Schoffelen JM (2011). FieldTrip: open source software for advanced analysis of MEG, EEG, and invasive electrophysiological data. *Computational Intelligence and Neuroscience*, 2011, 156869. DOI: 10.1155/2011/156869. <https://doi.org/10.1155/2011/156869>
    - **Supports:** background. FieldTrip builds forward models for a given sensor set and leaves the layout choice to the user.
- Tadel F, Baillet S, Mosher JC, Pantazis D, Leahy RM (2011). Brainstorm: a user-friendly application for MEG/EEG analysis. *Computational Intelligence and Neuroscience*, 2011, 879716. DOI: 10.1155/2011/879716. <https://doi.org/10.1155/2011/879716>
    - **Supports:** the closest graphical analogue, and the general aim of an approachable EEG interface. Its stated aim is to connect researchers with established methods through a simple graphical interface. It has no layout search or comparison.

### Forward solvers and head-model builders

- Akalin Acar Z, Makeig S (2010). Neuroelectromagnetic Forward Head Modeling Toolbox. *Journal of Neuroscience Methods*, 190(2), 258–270. DOI: 10.1016/j.jneumeth.2010.04.031. <https://doi.org/10.1016/j.jneumeth.2010.04.031>
    - **Supports:** background. It builds realistic boundary and finite element head models for EEGLAB; Kappel et al. (2019) used it to evaluate ear-EEG configurations.
- Gramfort A, Papadopoulo T, Olivi E, Clerc M (2010). OpenMEEG: opensource software for quasistatic bioelectromagnetics. *BioMedical Engineering OnLine*, 9, 45. DOI: 10.1186/1475-925X-9-45. <https://doi.org/10.1186/1475-925X-9-45>
    - **Supports:** background. It is a boundary element forward solver, an alternative to the finite element method used here. It does not design layouts.
- Medani T, Garcia-Prieto J, Tadel F, Antonakakis M, Erdbrügger T, Höltershinken M, et al. (2023). Brainstorm-DUNEuro: an integrated and user-friendly finite element method for modeling electromagnetic brain activity. *NeuroImage*, 267, 119851. DOI: 10.1016/j.neuroimage.2022.119851. <https://doi.org/10.1016/j.neuroimage.2022.119851>
    - **Supports:** the closest analogue combining a graphical interface with a finite element forward model. It stops at the forward solution and has no layout search or scoring.
- Schrader S, Westhoff A, Piastra MC, Miinalainen T, Pursiainen S, Vorwerk J, et al. (2021). DUNEuro—a software toolbox for forward modeling in bioelectromagnetism. *PLOS ONE*, 16(6), e0252431. DOI: 10.1371/journal.pone.0252431. <https://doi.org/10.1371/journal.pone.0252431>
    - **Supports:** background. It is an open-source finite element forward engine and does not choose sensors.
- Vorwerk J, Oostenveld R, Piastra MC, Magyari L, Wolters CH (2018). The FieldTrip-SimBio pipeline for EEG forward solutions. *BioMedical Engineering OnLine*, 17, 37. DOI: 10.1186/s12938-018-0463-y. <https://doi.org/10.1186/s12938-018-0463-y>
    - **Supports:** background. It computes finite element forward solutions for a user-given electrode set.

### EEG simulators

- Barzegaran E, Bosse S, Kohler PJ, Norcia AM (2019). EEGSourceSim: a framework for realistic simulation of EEG scalp data using MRI-based forward models and biologically plausible signals and noise. *Journal of Neuroscience Methods*, 328, 108377. DOI: 10.1016/j.jneumeth.2019.108377. <https://doi.org/10.1016/j.jneumeth.2019.108377>
    - **Supports:** signal simulation through forward models with a user-set SNR. It simulates on a given montage and does not score layouts.
- Haufe S, Ewald A (2019). A simulation framework for benchmarking EEG-based brain connectivity estimation methodologies. *Brain Topography*, 32(4), 625–642. DOI: 10.1007/s10548-016-0498-y. <https://doi.org/10.1007/s10548-016-0498-y>
    - **Supports:** background on simulation for benchmarking. [Published online in 2016; the issue is dated 2019.]
- Herdman AT (2021). SimMEEG software for simulating event-related MEG and EEG data with underlying functional connectivity. *Journal of Neuroscience Methods*, 350, 109017. DOI: 10.1016/j.jneumeth.2020.109017. <https://doi.org/10.1016/j.jneumeth.2020.109017>
    - **Supports:** background on graphical simulation tools. It focuses on connectivity, not layouts.
- Krol LR, Pawlitzki J, Lotte F, Gramann K, Zander TO (2018). SEREEGA: simulating event-related EEG activity. *Journal of Neuroscience Methods*, 309, 13–24. DOI: 10.1016/j.jneumeth.2018.08.001. <https://doi.org/10.1016/j.jneumeth.2018.08.001>
    - **Supports:** simulating EEG against a known ground truth to evaluate methods. It has no layout search or scoring.

### Array and montage design tools in other modalities

- Aasted CM, Yücel MA, Cooper RJ, Dubb J, Tsuzuki D, Becerra L, et al. (2015). Anatomical guidance for functional near-infrared spectroscopy: AtlasViewer tutorial. *Neurophotonics*, 2(2), 020801. DOI: 10.1117/1.NPh.2.2.020801. <https://doi.org/10.1117/1.NPh.2.2.020801>
    - **Supports:** an fNIRS analogue of a layout design and evaluation interface. It estimates sensitivity to brain regions and evaluates placement variability, with manual design rather than search.
- Brigadoi S, Salvagnin D, Fischetti M, Cooper RJ (2018). Array Designer: automated optimized array design for functional near-infrared spectroscopy. *Neurophotonics*, 5(3), 035010. DOI: 10.1117/1.NPh.5.3.035010. <https://doi.org/10.1117/1.NPh.5.3.035010>
    - **Supports:** automated array search under hardware constraints, the strongest analogue in another modality. The authors describe manual optode placement as difficult, slow and subjective.
- Haber I, Jackson A, Thielscher A, Hai A, Tononi G (2026). TI-Toolbox: an open-source software for temporal interference stimulation research. *Brain Stimulation*, 19(1), 103016. DOI: 10.1016/j.brs.2025.103016. <https://doi.org/10.1016/j.brs.2025.103016>
    - **Supports:** montage search on a SimNIBS model with a graphical interface, a command line and containerized deployment. It addresses stimulation, not EEG recording.
- Huang Y, Thomas C, Datta A, Parra LC (2018). Optimized tDCS for targeting multiple brain regions: an integrated implementation. In: *2018 40th Annual International Conference of the IEEE Engineering in Medicine and Biology Society (EMBC)*, pp. 3545–3548. IEEE. DOI: 10.1109/EMBC.2018.8513034. <https://doi.org/10.1109/EMBC.2018.8513034>
    - **Supports:** montage optimization added to an open finite element pipeline for stimulation.
- Huang Y, Datta A, Bikson M, Parra LC (2019). Realistic volumetric-approach to simulate transcranial electric stimulation—ROAST—a fully automated open-source pipeline. *Journal of Neural Engineering*, 16(5), 056006. DOI: 10.1088/1741-2552/ab208d. <https://doi.org/10.1088/1741-2552/ab208d>
    - **Supports:** background. It is an automated finite element pipeline for stimulation, with no recording-layout design.
- Willis JA, Wright CE, Zhu R, Ruan Y, Stallings J, Abrego AM, et al. (2026). Optimizing electrode placement and information capacity for local field potentials in cortex. *NeuroImage*, 327, 121747. DOI: 10.1016/j.neuroimage.2026.121747. <https://doi.org/10.1016/j.neuroimage.2026.121747>
    - **Supports:** the closest analogue that optimizes electrode placement from finite element lead fields, for invasive electrodes. It uses a genetic algorithm that maximizes information capacity.
- Zimeo Morais GA, Balardin JB, Sato JR (2018). fNIRS Optodes' Location Decider (fOLD): a toolbox for probe arrangement guided by brain regions-of-interest. *Scientific Reports*, 8, 3341. DOI: 10.1038/s41598-018-21716-z. <https://doi.org/10.1038/s41598-018-21716-z>
    - **Supports:** choosing from a fixed set of named positions with a forward model, as EEGLayoutLab does with 10-05 names. It targets regions of interest rather than comparing against a whole-head reference.

## Data standards and reproducible research software

These works support coordinate import, the exports, the delivery packages with checksums and recorded model and runtime identities, and the public result library.

### Data and coordinate standards

- Appelhoff S, Sanderson M, Brooks T, van Vliet M, Quentin R, Holdgraf C, et al. (2019). MNE-BIDS: organizing electrophysiological data into the BIDS format and facilitating their analysis. *Journal of Open Source Software*, 4(44), 1896. DOI: 10.21105/joss.01896. <https://doi.org/10.21105/joss.01896>
    - **Supports:** coordinate import from BIDS and the MNE-Python export; it is the reference implementation they align with.
- Delorme A, Truong D, Martinez-Cancino R, Pernet C, Sivagnanam S, Yoshimoto K, et al. (2021). Tools for importing and evaluating BIDS-EEG formatted data. In: *2021 10th International IEEE/EMBS Conference on Neural Engineering (NER)*, pp. 210–213. IEEE. DOI: 10.1109/NER49283.2021.9441399. <https://doi.org/10.1109/NER49283.2021.9441399>
    - **Supports:** background on BIDS-EEG import in EEGLAB.
- Gorgolewski KJ, Auer T, Calhoun VD, Craddock RC, Das S, Duff EP, et al. (2016). The brain imaging data structure, a format for organizing and describing outputs of neuroimaging experiments. *Scientific Data*, 3, 160044. DOI: 10.1038/sdata.2016.44. <https://doi.org/10.1038/sdata.2016.44>
    - **Supports:** coordinate import. It defines BIDS.
- Niso G, Gorgolewski KJ, Bock E, Brooks TL, Flandin G, Gramfort A, et al. (2018). MEG-BIDS, the brain imaging data structure extended to magnetoencephalography. *Scientific Data*, 5, 180110. DOI: 10.1038/sdata.2018.110. <https://doi.org/10.1038/sdata.2018.110>
    - **Supports:** coordinate import. It introduced the coordinate-system conventions later shared with EEG-BIDS.
- Pernet CR, Appelhoff S, Gorgolewski KJ, Flandin G, Phillips C, Delorme A, Oostenveld R (2019). EEG-BIDS, an extension to the brain imaging data structure for electroencephalography. *Scientific Data*, 6, 103. DOI: 10.1038/s41597-019-0104-8. <https://doi.org/10.1038/s41597-019-0104-8>
    - **Supports:** coordinate import from `electrodes.tsv` and `coordsystem.json`, the sidecar files it defines.

### Reproducible practice and shared platforms

- Barker M, Chue Hong NP, Katz DS, Lamprecht AL, Martinez-Ortiz C, Psomopoulos F, et al. (2022). Introducing the FAIR Principles for research software. *Scientific Data*, 9, 622. DOI: 10.1038/s41597-022-01710-x. <https://doi.org/10.1038/s41597-022-01710-x>
    - **Supports:** open-source release, versioned identities and command-line parity with the web interface.
- Delorme A, Truong D, Youn C, Sivagnanam S, Stirm C, Yoshimoto K, et al. (2022). NEMAR: an open access data, tools and compute resource operating on neuroelectromagnetic data. *Database*, 2022, baac096. DOI: 10.1093/database/baac096. <https://doi.org/10.1093/database/baac096>
    - **Supports:** an analogue of a web compute service with shared results for electrophysiology.
- Gorgolewski KJ, Poldrack RA (2016). A practical guide for improving transparency and reproducibility in neuroimaging research. *PLoS Biology*, 14(7), e1002506. DOI: 10.1371/journal.pbio.1002506. <https://doi.org/10.1371/journal.pbio.1002506>
    - **Supports:** background on reproducible neuroimaging practice.
- Halchenko Y, Meyer K, Poldrack B, Solanky D, Wagner A, Gors J, et al. (2021). DataLad: distributed system for joint management of code, data, and their relationship. *Journal of Open Source Software*, 6(63), 3262. DOI: 10.21105/joss.03262. <https://doi.org/10.21105/joss.03262>
    - **Supports:** an analogue for delivery packages with checksums and recorded identities.
- Hayashi S, Caron BA, Heinsfeld AS, Vinci-Booher S, McPherson B, Bullock DN, et al. (2024). brainlife.io: a decentralized and open-source cloud platform to support neuroscience research. *Nature Methods*, 21(5), 809–813. DOI: 10.1038/s41592-024-02237-2. <https://doi.org/10.1038/s41592-024-02237-2>
    - **Supports:** an analogue of the web application with a persistent queue and a public library.
- Lamprecht AL, Garcia L, Kuzak M, Martinez C, Arcila R, Martin Del Pico E, et al. (2020). Towards FAIR principles for research software. *Data Science*, 3(1), 37–59. DOI: 10.3233/DS-190026. <https://doi.org/10.3233/DS-190026>
    - **Supports:** background; it is the precursor to the FAIR principles for research software. [Published online in 2019; the issue is dated 2020.]
- Markiewicz CJ, Gorgolewski KJ, Feingold F, Blair R, Halchenko YO, Miller E, et al. (2021). The OpenNeuro resource for sharing of neuroscience data. *eLife*, 10, e71774. DOI: 10.7554/eLife.71774. <https://doi.org/10.7554/eLife.71774>
    - **Supports:** an analogue for the public result library.
- Pernet C, Garrido MI, Gramfort A, Maurits N, Michel CM, Pang E, et al. (2020). Issues and recommendations from the OHBM COBIDAS MEEG committee for reproducible EEG and MEG research. *Nature Neuroscience*, 23(12), 1473–1483. DOI: 10.1038/s41593-020-00709-0. <https://doi.org/10.1038/s41593-020-00709-0>
    - **Supports:** recording electrode positions, the head model and the forward-model identity with each result, items these recommendations ask authors to report.
- Sandve GK, Nekrutenko A, Taylor J, Hovig E (2013). Ten simple rules for reproducible computational research. *PLoS Computational Biology*, 9(10), e1003285. DOI: 10.1371/journal.pcbi.1003285. <https://doi.org/10.1371/journal.pcbi.1003285>
    - **Supports:** recorded model and runtime identities and exact result reuse. The rules ask authors to track how results were produced, record versions and keep raw data.
- Smith AM, Katz DS, Niemeyer KE, FORCE11 Software Citation Working Group (2016). Software citation principles. *PeerJ Computer Science*, 2, e86. DOI: 10.7717/peerj-cs.86. <https://doi.org/10.7717/peerj-cs.86>
    - **Supports:** citable releases and a recorded software identity.
- Wilkinson MD, Dumontier M, Aalbersberg IJ, Appleton G, Axton M, Baak A, et al. (2016). The FAIR Guiding Principles for scientific data management and stewardship. *Scientific Data*, 3, 160018. DOI: 10.1038/sdata.2016.18. <https://doi.org/10.1038/sdata.2016.18>
    - **Supports:** the public result library and persistent identifiers.
- Wilson G, Aruliah DA, Brown CT, Chue Hong NP, Davis M, Guy RT, et al. (2014). Best practices for scientific computing. *PLoS Biology*, 12(1), e1001745. DOI: 10.1371/journal.pbio.1001745. <https://doi.org/10.1371/journal.pbio.1001745>
    - **Supports:** background on practices for scientific software.

## Interface design

These works relate to the structure of the interface: the five areas (Workspace, Layouts, Analysis, Findings and Documentation) with a page per layout, the "Start here" panel, the term hints, and keeping rarely needed detail out of the way. Most of the evidence comes from general or educational software, not from scientific web tools.

### First use and task-oriented entry

- Andersen E, O'Rourke E, Liu Y-E, Snider R, Lowdermilk J, Truong D, Cooper S, Popović Z (2012). The impact of tutorials on games of varying complexity. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '12)*, pp. 59–68. New York, NY: ACM. DOI: 10.1145/2207676.2207687. <https://doi.org/10.1145/2207676.2207687>
    - **Supports:** keeping first-use guidance short. In a field study with more than 45,000 players, tutorials increased play time by up to 29 % in the most complex game.
    - **Limits:** tutorials did not significantly improve engagement in the two simpler games.
- Carroll JM, Rosson MB (1987). Paradox of the active user. In: Carroll JM (ed.), *Interfacing Thought: Cognitive Aspects of Human-Computer Interaction*, pp. 80–111. Cambridge, MA: MIT Press. ISBN 978-0-262-03125-7. No DOI.
    - **Supports:** task entries in the "Start here" panel and term hints shown while the user works. Users want to get work done and skip learning, even when some learning would help them later, and they read a new system through what they already know. [Pages from library records; the chapter was not available in full, and its content is known from summaries.]
- Carroll JM, Smith-Kerker P, Ford J, Mazur-Rimetz S (1987). The Minimal Manual. *Human-Computer Interaction*, 3(2), 123–153. DOI: 10.1207/s15327051hci0302_2. <https://doi.org/10.1207/s15327051hci0302_2>
    - **Supports:** short, task-first guidance with a link to the full chapter. A shorter manual that supports error recognition and recovery gave more efficient learning than a commercial manual in two experiments. [Other records give Smith-Kerker PL, Ford JR and Mazur-Rimetz SA.]
- Carroll JM (1990). *The Nurnberg Funnel: Designing Minimalist Instruction for Practical Computer Skill*. Cambridge, MA: MIT Press. ISBN 978-0-262-03163-9. No DOI.
    - **Supports:** minimalist instruction: starting from real tasks, with less reading. [Finding not re-read; subtitle as normally cited.]
- Froehlich M, Kobiella C, Schmidt A, Alt F (2021). Is it better with onboarding? Improving first-time cryptocurrency app experiences. In: *Designing Interactive Systems Conference 2021 (DIS '21)*, pp. 78–89. New York, NY: ACM. DOI: 10.1145/3461778.3462047. <https://doi.org/10.1145/3461778.3462047>
    - **Supports:** first-use guidance for complex tools built on minimalist principles. Onboarding improved perceived usability for first-time users of feature-rich apps.
    - **Limits:** the samples were small (16 interviews and 16 evaluations), and only perceived usability was measured.
- Novick DG, Ward K (2006). Why don't people read the manual? In: *Proceedings of the 24th Annual ACM International Conference on Design of Communication (SIGDOC '06)*, pp. 11–18. New York, NY: ACM. DOI: 10.1145/1166324.1166329. <https://doi.org/10.1145/1166324.1166329>
    - **Supports:** term hints placed next to the term. In interviews with 25 users, people avoided manuals and online help; they named difficulty finding search terms and help that did not explain enough.
- Rettig M (1991). Nobody reads documentation. *Communications of the ACM*, 34(7), 19–24. DOI: 10.1145/105783.105788. <https://doi.org/10.1145/105783.105788>
    - **Supports:** help built into the interface, as historical framing. It is an opinion column, not empirical research.

### Learnability and contextual help

- Chilana PK, Ko AJ, Wobbrock JO (2012). LemonAid: selection-based crowdsourced contextual help for web applications. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '12)*, pp. 1549–1558. New York, NY: ACM. DOI: 10.1145/2207676.2208620. <https://doi.org/10.1145/2207676.2208620>
    - **Supports:** help attached to the term itself. Users' text queries for help are often imprecise; selecting the relevant interface element found a result for 90 % of requests.
- Grossman T, Fitzmaurice G, Attar R (2009). A survey of software learnability: metrics, methodologies and guidelines. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '09)*, pp. 649–658. New York, NY: ACM. DOI: 10.1145/1518701.1518803. <https://doi.org/10.1145/1518701.1518803>
    - **Supports:** treating first-use learnability as a distinct quality that can be evaluated. A question-suggestion protocol found significantly more learnability problems than think-aloud.
- Grossman T, Fitzmaurice G (2010). ToolClips: an investigation of contextual video assistance for functionality understanding. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '10)*, pp. 1515–1524. New York, NY: ACM. DOI: 10.1145/1753326.1753552. <https://doi.org/10.1145/1753326.1753552>
    - **Supports:** short help attached to an interface element, with a path to richer content. Users completed seven times as many unfamiliar tasks as with a commercial online help system.
    - **Limits:** the help opened on hover in a desktop application, whereas the term hints open on click or key press.
- Horvitz E (1999). Principles of mixed-initiative user interfaces. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '99)*, pp. 159–166. New York, NY: ACM Press. DOI: 10.1145/302979.303030. <https://doi.org/10.1145/302979.303030>
    - **Supports:** a dismissible "Start here" panel that can be reopened. The paper sets out principles for combining automated assistance with direct manipulation. [Individual principles not re-read.]
- Kelleher C, Pausch R (2005). Stencils-based tutorials: design and evaluation. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '05)*, pp. 541–550. New York, NY: ACM. DOI: 10.1145/1054972.1055047. <https://doi.org/10.1145/1054972.1055047>
    - **Supports:** guidance placed in the interface. Overlays placed on the application let users finish a tutorial 26 % faster, with fewer errors.
    - **Limits:** in-context guidance improved completion, not learning.

### Progressive disclosure and decluttering

- Carroll JM, Carrithers C (1984). Training wheels in a user interface. *Communications of the ACM*, 27(8), 800–806. DOI: 10.1145/358198.358218. <https://doi.org/10.1145/358198.358218>
    - **Supports:** keeping advanced or irrelevant controls out of a new user's way. Blocking common error states gave substantially faster learning and better comprehension.
- Findlater L, McGrenere J (2010). Beyond performance: feature awareness in personalized interfaces. *International Journal of Human-Computer Studies*, 68(3), 121–137. DOI: 10.1016/j.ijhcs.2009.10.002. <https://doi.org/10.1016/j.ijhcs.2009.10.002>
    - **Limits:** reducing the visible feature set may lower users' awareness of the full feature set. [Finding not re-read; topic from the title.]
- McGrenere J, Baecker RM, Booth KS (2002). An evaluation of a multiple interface design solution for bloated software. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '02)*, pp. 164–170. New York, NY: ACM. DOI: 10.1145/503376.503406. <https://doi.org/10.1145/503376.503406>
    - **Supports:** a reduced default view with the full view one action away, under the user's control. Users who could switch between a personal and a full interface navigated and learned better, and reported more satisfaction and control.
- Nielsen J, Molich R (1990). Heuristic evaluation of user interfaces. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '90)*, pp. 249–256. New York, NY: ACM. DOI: 10.1145/97243.97281. <https://doi.org/10.1145/97243.97281>
    - **Supports:** reviewing the interface against heuristics. Single evaluators found only 20–51 % of usability problems, while the combined results of three to five evaluators did well.
- Nielsen J (1993). *Usability Engineering*. Boston, MA: Academic Press. ISBN 978-0-12-518406-9. DOI: 10.1016/C2009-0-21512-1. <https://doi.org/10.1016/C2009-0-21512-1>
    - **Supports:** usability heuristics and learnability as a usability attribute. [Finding not re-read; place of publication as normally cited.]
- Nielsen J (1994). Enhancing the explanatory power of usability heuristics. In: *Proceedings of the SIGCHI Conference on Human Factors in Computing Systems (CHI '94)*, pp. 152–158. New York, NY: ACM. DOI: 10.1145/191666.191729. <https://doi.org/10.1145/191666.191729>
    - **Supports:** the revised set of usability heuristics. [Finding not re-read; topic from the title.]
- Pirolli P, Card S (1999). Information foraging. *Psychological Review*, 106(4), 643–675. DOI: 10.1037/0033-295X.106.4.643. <https://doi.org/10.1037/0033-295X.106.4.643>
    - **Supports:** labels named after the user's goals. [Finding not re-read; topic from the title.]
- Shneiderman B (1996). The eyes have it: a task by data type taxonomy for information visualizations. In: *Proceedings 1996 IEEE Symposium on Visual Languages*, pp. 336–343. Los Alamitos, CA: IEEE Computer Society Press. DOI: 10.1109/VL.1996.545307. <https://doi.org/10.1109/VL.1996.545307>
    - **Supports:** the order of the interface: an overview of layouts first, then a page per layout, then detail on demand. The paper proposes showing an overview before zooming, filtering and showing details on request. [Crossref gives no issue date, and OpenAlex wrongly gives 2002.]
- Shneiderman B (2003). Promoting universal usability with multi-layer interface design. In: *Proceedings of the 2003 Conference on Universal Usability (CUU '03)*, pp. 1–8. New York, NY: ACM. DOI: 10.1145/957205.957206. <https://doi.org/10.1145/957205.957206>
    - **Supports:** starting new users with a limited feature set, such as the collapsed task list. In multi-layer interfaces, users move to higher layers when they need to. [Crossref dates the record 2002, which is an error; the proceedings are from 2003.]

### Worked examples and cognitive load

- Atkinson RK, Derry SJ, Renkl A, Wortham D (2000). Learning from examples: instructional principles from the worked examples research. *Review of Educational Research*, 70(2), 181–214. DOI: 10.3102/00346543070002181. <https://doi.org/10.3102/00346543070002181>
    - **Supports:** an example layout one step from evaluating the user's own positions, with labelled scores. Effective instruction places examples close to matching practice problems.
- Kalyuga S, Ayres P, Chandler P, Sweller J (2003). The expertise reversal effect. *Educational Psychologist*, 38(1), 23–31. DOI: 10.1207/S15326985EP3801_4. <https://doi.org/10.1207/S15326985EP3801_4>
    - **Supports:** remembering when the "Start here" panel was dismissed. Techniques that help inexperienced learners can lose their effect or harm more experienced ones.
- Mayer RE, Moreno R (2003). Nine ways to reduce cognitive load in multimedia learning. *Educational Psychologist*, 38(1), 43–52. DOI: 10.1207/S15326985EP3801_6. <https://doi.org/10.1207/S15326985EP3801_6>
    - **Supports:** reducing extraneous material and introducing key terms early. The paper analyses five overload scenarios and ways to reduce load in each. [The individual methods were not re-read.]
- Mayer RE (2020). *Multimedia Learning* (3rd ed.). Cambridge: Cambridge University Press. ISBN 978-1-107-18750-4. DOI: 10.1017/9781316941355. <https://doi.org/10.1017/9781316941355>
    - **Supports:** background on multimedia learning principles. [Finding not re-read; bibliographic record checked in Crossref.]
- Sweller J, Cooper GA (1985). The use of worked examples as a substitute for problem solving in learning algebra. *Cognition and Instruction*, 2(1), 59–89. DOI: 10.1207/s1532690xci0201_3. <https://doi.org/10.1207/s1532690xci0201_3>
    - **Supports:** a fully evaluated example layout as a starting point. Worked examples took much less time to process than conventional problems.
    - **Limits:** the benefit was specific to problems with the same structure.
- Sweller J (1988). Cognitive load during problem solving: effects on learning. *Cognitive Science*, 12(2), 257–285. DOI: 10.1207/s15516709cog1202_4. <https://doi.org/10.1207/s15516709cog1202_4>
    - **Supports:** starting from an example rather than a blank page. Conventional problem solving uses capacity that is then not available for learning.

### Jargon, definitions and help-seeking

- Aleven V, Koedinger KR (2000). Limitations of student control: do students know when they need help? In: Gauthier G, Frasson C, VanLehn K (eds.), *Intelligent Tutoring Systems: 5th International Conference, ITS 2000 Montréal, Canada, June 19–23, 2000 Proceedings*, pp. 292–303. Berlin, Heidelberg: Springer. ISBN 978-3-540-67655-3. DOI: 10.1007/3-540-45108-0_33. <https://doi.org/10.1007/3-540-45108-0_33>
    - **Limits:** learners may not use on-demand glossaries and hints when they would help. [Finding not re-read; topic from the title. The book appeared in Lecture Notes in Computer Science; the volume number, 1839, was not confirmed.]
- Aleven V, Stahl E, Schworm S, Fischer F, Wallace R (2003). Help seeking and help design in interactive learning environments. *Review of Educational Research*, 73(3), 277–320. DOI: 10.3102/00346543073003277. <https://doi.org/10.3102/00346543073003277>
    - **Limits:** effective help-seeking is associated with better learning, but learners do not use on-demand help effectively. Term hints that wait to be opened may go unused.
- Bullock OM, Colón Amill D, Shulman HC, Dixon GN (2019). Jargon as a barrier to effective science communication: evidence from metacognition. *Public Understanding of Science*, 28(7), 845–853. DOI: 10.1177/0963662519865687. <https://doi.org/10.1177/0963662519865687>
    - **Supports:** plain-language labels. Jargon impaired the processing of scientific information in an experiment with 650 participants.
    - **Limits:** the participants were lay readers, not EEG researchers.
- Shulman HC, Dixon GN, Bullock OM, Colón Amill D (2020). The effects of jargon on processing fluency, self-perceptions, and scientific engagement. *Journal of Language and Social Psychology*, 39(5–6), 579–597. DOI: 10.1177/0261927X20902177. <https://doi.org/10.1177/0261927X20902177>
    - **Supports:** the cost of jargon, the reason for term hints.
    - **Limits:** jargon disrupted fluent processing even when definitions were provided, so definitions alone are not enough. The participants were lay readers.

### Accessibility of disclosure controls

- Campbell A, Adams C, Bradley Montgomery R, Cooper M, Kirkpatrick A (eds.) (2023). *Web Content Accessibility Guidelines (WCAG) 2.2*. W3C Recommendation, 5 October 2023; updated 12 December 2024. <https://www.w3.org/TR/2024/REC-WCAG22-20241212/>
    - **Supports:** term hints that open on click or key press and close with Escape. Success criterion 1.4.13 requires extra content shown on hover or focus to be dismissible, hoverable and persistent.
- Diggs J, Nurthen J, Cooper M, MacLeod C (eds.) (2023). *Accessible Rich Internet Applications (WAI-ARIA) 1.2*. W3C Recommendation, 6 June 2023. <https://www.w3.org/TR/2023/REC-wai-aria-1.2-20230606/>
    - **Supports:** the term hint as a button with the `aria-expanded` state; the specification defines the roles and states it uses. [Definition wording not re-read.]
- Kirkpatrick A, O Connor J, Campbell A, Cooper M (eds.) (2018). *Web Content Accessibility Guidelines (WCAG) 2.1*. W3C Recommendation, 5 June 2018; republished 21 September 2023, 12 December 2024 and 6 May 2025. <https://www.w3.org/TR/2018/REC-WCAG21-20180605/>
    - **Supports:** the accessibility requirements for content shown on hover or focus. [Whether success criterion 1.4.13 first appeared in this version was not re-checked.]
- W3C Web Accessibility Initiative (n.d.). ARIA Authoring Practices Guide (APG): Disclosure (Show/Hide) Pattern. Web page, accessed 24 November 2026. <https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/>
    - **Supports:** the term hint control. A disclosure is a button with `aria-expanded` set to true when its content is shown and false when hidden; Enter or Space toggles it.

### Usability of scientific software

- Bolchini D, Finkelstein A, Perrone V, Nagl S (2009). Better bioinformatics through usability analysis. *Bioinformatics*, 25(3), 406–412. DOI: 10.1093/bioinformatics/btn633. <https://doi.org/10.1093/bioinformatics/btn633>
    - **Supports:** attention to navigation structure. Usability evaluation of web bioinformatics resources found navigation and search problems that hinder users from finding what they need.
- Lee BD (2018). Ten simple rules for documenting scientific software. *PLOS Computational Biology*, 14(12), e1006561. DOI: 10.1371/journal.pcbi.1006561. <https://doi.org/10.1371/journal.pcbi.1006561>
    - **Supports:** the example layout, the "Start here" panel as a quickstart, and links from the interface to the method chapters. Its rules include giving many examples and a quickstart guide.
- List M, Ebert P, Albrecht F (2017). Ten simple rules for developing usable software in computational biology. *PLOS Computational Biology*, 13(1), e1005265. DOI: 10.1371/journal.pcbi.1005265. <https://doi.org/10.1371/journal.pcbi.1005265>
    - **Supports:** exposing only the parameters a user must set and getting users started quickly. It argues that good usability is needed for a tool to be widely accepted.
- Macaulay C, Sloan D, Jiang X, Forbes P, Loynton S, Swedlow JR, Gregor P (2009). Usability and user-centered design in scientific software development. *IEEE Software*, 26(1), 96–102. DOI: 10.1109/MS.2009.27. <https://doi.org/10.1109/MS.2009.27>
    - **Supports:** user-centred design for scientific tools, from a case study of image-data software for cell biologists.
- Mangul S, Mosqueiro T, Abdill RJ, Duong D, Mitchell K, Sarwal V, et al. (2019). Challenges and recommendations to improve the installability and archival stability of omics computational tools. *PLOS Biology*, 17(6), e3000333. DOI: 10.1371/journal.pbio.3000333. <https://doi.org/10.1371/journal.pbio.3000333>
    - **Supports:** easy access to scientific tools. Of 98 tools tested, 51 % were easy to install and 28 % could not be installed, and easy installation was associated with more citations.
    - **Limits:** the link between ease of installation and citations is correlational.
- Pavelin K, Cham JA, de Matos P, Brooksbank C, Cameron G, Steinbeck C (2012). Bioinformatics meets user-centred design: a perspective. *PLoS Computational Biology*, 8(7), e1002554. DOI: 10.1371/journal.pcbi.1002554. <https://doi.org/10.1371/journal.pcbi.1002554>
    - **Supports:** user-centred design for scientific resources. Life scientists trust the data but often find the interfaces hard to use and navigate.
- Taschuk M, Wilson G (2017). Ten simple rules for making research software more robust. *PLOS Computational Biology*, 13(4), e1005412. DOI: 10.1371/journal.pcbi.1005412. <https://doi.org/10.1371/journal.pcbi.1005412>
    - **Supports:** a runnable example and easy common operations.

## Software documentation and web resources

These are web pages, not journal articles. They are cited for software conventions, code and data, or as practitioner material that supplements the peer-reviewed works above. Page titles are given as they appeared in November 2026.

### Software documentation, code and data

- BIDS contributors (n.d.). Electroencephalography. Brain Imaging Data Structure specification 1.11.2, modality-specific files. Web page. <https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html>
    - **Supports:** coordinate import and export with `electrodes.tsv` and `coordsystem.json`: the first four electrode columns, the required coordinate-system file and the description required for an `Other` coordinate system. The data standard itself is described by Pernet et al. (2019).
- FreeSurfer developers (n.d.). CorticalParcellation. FreeSurfer Wiki. Web page. <https://www.freesurfer.net/fswiki/CorticalParcellation>
    - **Supports:** the Desikan–Killiany cortical labels from which the six source regions (DK40) are grouped, with Desikan et al. (2006).
- IXI dataset (n.d.). IXI Dataset. Brain Development. Web page; data licensed under CC BY-SA 3.0. <https://brain-development.org/ixi-dataset/>
    - **Supports:** the `ixi` head packages, segmented with SimNIBS `charm`, that check whether a conclusion holds beyond the Ernie head model.
- MNE-Python developers (n.d.). Interpolate bad channels for MEG/EEG channels. MNE 1.6 documentation, example gallery. Web page. <https://mne.tools/1.6/auto_examples/preprocessing/interpolate_bad_channels.html>
    - **Supports:** forward-model interpolation of EEG channels as an option in standard software. The example documents a minimum-norm option for EEG next to the spline default.
    - **Limits:** it is software documentation, not a peer-reviewed comparison of the two methods.
- MNE-Tools contributors (n.d.). dipole-simulator: interactive demonstration of how dipole location and orientation affect MEG and EEG sensor signals. GitHub repository mne-tools/dipole-simulator. <https://github.com/mne-tools/dipole-simulator>
    - **Supports:** the source–field interaction shown in signal simulation follows this demonstration. Its code was not ported.
- SimNIBS Developers (n.d.). Analyzing Simulations: ROI analysis using surfaces. SimNIBS 4.6.0 documentation, tutorial. Web page. <https://simnibs.github.io/simnibs/build/html/tutorial/analysis.html#roi-analysis-using-surfaces>
    - **Supports:** the surface regions of interest used to build the six source regions on the cortical surface.
- SimNIBS Developers (n.d.). Calculation of EEG Leadfields. SimNIBS 4.6.0 documentation, tutorial. Web page. <https://simnibs.github.io/simnibs/build/html/tutorial/advanced/eeg_leadfields.html>
    - **Supports:** the FEM lead fields by reciprocity. `FixedMeshLeadfield.evaluate` follows the theory and workflow of this page.
- SimNIBS Developers (n.d.). Coordinates in SimNIBS. SimNIBS 4.6.0 documentation. Web page. <https://simnibs.github.io/simnibs/build/html/documentation/coordinates.html>
    - **Supports:** coordinate import in the Ernie native frame and in MNI space, following the SimNIBS coordinate conventions.
- SimNIBS Developers (n.d.). Leadfield-free TES Optimization. SimNIBS 4.6.0 documentation, tutorial. Web page. <https://simnibs.github.io/simnibs/build/html/tutorial/tes_flex_opt.html>
    - **Supports:** background on electrode optimization in SimNIBS for stimulation. The page asks users to cite the bioRxiv preprint of Weise et al.; this list cites the journal version (Weise et al. 2025).
- SimNIBS Developers (2023). Example dataset for SimNIBS 4 (version 2). GitHub release v4.1 of simnibs/example-dataset, published 2 October 2023. Licence CC BY-NC 4.0. <https://github.com/simnibs/example-dataset/releases/tag/v4.1>
    - **Supports:** the source of the Ernie head model.
- TBBL-UTHealth (n.d.). SEPIO: code repository for a publication on optimization of electrode placement. GitHub repository TBBL-UTHealth/SEPIO. <https://github.com/TBBL-UTHealth/SEPIO>
    - **Supports:** the organisation of the signal-simulation workflow. Its optimization objectives and code were not ported; this project keeps its fixed 64-electrode layouts and metric definitions.

### Practitioner articles, not peer reviewed

- Kendrick A (2020). Mobile Tutorials: Wasted Effort or Efficiency Boost? Nielsen Norman Group, 8 March 2020. <https://www.nngroup.com/articles/mobile-tutorials/>
    - **Supports:** contextual help over up-front tutorials, as a supplement to Andersen et al. (2012). [Figures not re-read and not stated here.]
- Kendrick A (2020). Mobile-App Onboarding: An Analysis of Components and Techniques. Nielsen Norman Group, 21 June 2020. <https://www.nngroup.com/articles/mobile-app-onboarding/>
    - **Supports:** keeping onboarding short and contextual, as a supplement to the peer-reviewed works on first use. [Not re-read in full.]
- Nielsen J (1994). 10 Usability Heuristics for User Interface Design. Nielsen Norman Group, 24 April 1994; last reviewed 30 January 2024. <https://www.nngroup.com/articles/ten-usability-heuristics/>
    - **Supports:** term hints and decluttering. Among the heuristics: use words and concepts familiar to the user, and leave out information that is irrelevant or rarely needed.
- Nielsen J (1998). Paradox of the Active User. Nielsen Norman Group, 4 October 1998. <https://www.nngroup.com/articles/paradox-of-the-active-user/>
    - **Supports:** a summary of Carroll and Rosson (1987), used as a readable pointer to the original chapter.

## What the literature does not establish

The reviews behind this list report the following gaps. Each gap is limited to the searches made, which covered indexed English-language publications through Crossref, PubMed, Semantic Scholar and web search, without a full systematic review of IEEE Xplore or Scopus.

- **No tool for restricted-region EEG layouts.** To our knowledge, as of November 2026, no published software or study searches or compares scalp EEG recording layouts confined to a scalp region and scores them against a whole-head reference under a finite element forward model. fNIRS and stimulation have such design tools (Brigadoi et al. 2018; Zimeo Morais et al. 2018; Saturnino, Siebner et al. 2019; Weise et al. 2025). Model-based channel selection, EEG simulation and forward models of artefacts do have precedents.
- **No forward-model study of forehead-only, periorbital or multi-region hair-free arrays.** Forward-model work on restricted arrays covers ear-centred arrays (Kappel, Makeig & Kidmose 2019; Meiser et al. 2020; Meiser, Knoll & Bleichner 2024; Yarici et al. 2023). Cap comparisons for forehead sites come from sleep devices.
- **No study trading density against coverage at a fixed channel count in a realistic finite element model**, other than Song et al. (2015), and none comparing full-head arrays with regionally confined arrays at equal channel count. No study quantifies the information lost from a whole-head to a region-confined array, or bounds interpolation accuracy outside the area covered by the electrodes.
- **No study of ranking stability.** Studies of head-model and conductivity error report changes in absolute error. No study measures how stable the relative ranking of layouts is across heads or conductivities.
- **No peer-reviewed definition of an LMMSE field reconstruction retention score.** The closest precedents are forward-model rank and resolution metrics (Molins et al. 2008; Hauk, Stenroos & Treder 2022). Related estimators and selection criteria are minimum-norm field mapping (Hämäläinen & Ilmoniemi 1994), rREST (Hu, Yao & Valdes-Sosa 2018), utility metrics for linear estimation (Bertrand 2018) and A-optimal design (Alexanderian et al. 2014). The exact formulation is this project's own construct. No peer-reviewed head-to-head comparison of minimum-norm and spline interpolation of EEG channels was found.
- **No approximation guarantee for the local radius search.** Known guarantees cover greedy selection of submodular criteria (Nemhauser, Wolsey & Fisher 1978; Krause, Singh & Guestrin 2008), not a local search over continuous positions. No peer-reviewed EEG study was found that maximizes mutual information or Fisher information directly over continuous scalp positions.
- **No benchmark of reference removal.** The case for comparing layouts in the reference-free space is theoretical (Geselowitz 1998) and based on simulation (Hu et al. 2018). No paper compares layout rankings with and without reference removal.
- **No reusable cardiac-field map and no ECG scalp simulator.** No openly available scalp topography of the cardiac field on a 10-05 grid was found; Dirlich et al. (1997) measured it in nine subjects without giving a reusable map. No published simulator models ECG interference at the scalp through a head model; HArtMuT (Harmening et al. 2022) covers eye and muscle sources. No study quantifies how ECG or EOG interference changes localization or layout rankings.
- **No measured dropout rate and no cross-device survey of hair and impedance.** No study reports how many channels typically drop out in 64-channel sessions; PREP (Bigdely-Shamlo et al. 2015) shows that bad channels are common but gives no rate. Evidence on how much hair raises dry-contact impedance is per device (Hua et al. 2019; Wang et al. 2024).
- **Interface gaps.** No empirical usability study of EEG or neuroimaging web tools, or of electrode-layout software, was found. No peer-reviewed controlled study was found of "Start here" panels or checklists on a web application's home page, of product tours, of empty states, or of remembering that onboarding was dismissed. No study compares inline definitions with glossary pages or hover tooltips for expert scientific users; the jargon studies use lay readers. No peer-reviewed study compares the accessibility of hover tooltips and click disclosures for keyboard or screen-reader users. Evidence linking usability to the adoption of scientific tools is correlational (Mangul et al. 2019).
