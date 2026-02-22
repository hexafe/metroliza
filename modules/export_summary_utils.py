import pandas as pd

from modules.stats_utils import safe_process_capability


def resolve_nominal_and_limits(header_group: pd.DataFrame):
    nom = round(header_group['NOM'].iloc[0], 3)
    upper_tolerance = round(header_group['+TOL'].iloc[0], 3)
    lower_tolerance = round(header_group['-TOL'].iloc[0], 3) if header_group['-TOL'].iloc[0] else 0

    return {
        'nom': nom,
        'usl': nom + upper_tolerance,
        'lsl': nom + lower_tolerance,
    }


def compute_measurement_summary(header_group: pd.DataFrame, usl: float, lsl: float, nom: float):
    meas = header_group['MEAS']
    sigma = meas.std()
    average = meas.mean()
    sample_size = meas.count()
    nok_count = header_group[(meas > usl) | (meas < lsl)]['MEAS'].count()

    cp, cpk = safe_process_capability(nom, usl, lsl, sigma, average)

    return {
        'minimum': meas.min(),
        'maximum': meas.max(),
        'sigma': sigma,
        'average': average,
        'median': meas.median(),
        'cp': cp,
        'cpk': cpk,
        'sample_size': sample_size,
        'nok_count': nok_count,
        'nok_pct': (nok_count / sample_size) if sample_size else 0,
    }
