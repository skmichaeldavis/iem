import pandas as pd
import datetime
import psycopg2
from pandas.io.sql import read_sql
from collections import OrderedDict
from pyiem.meteorology import gdd
from pyiem.datatypes import temperature, distance
from pyiem.util import get_autoplot_context
from scipy import stats

STATIONS = OrderedDict([
        ('ames', 'Central (Ames)'),
        ('cobs', 'Central (COBS)'),
        ('crawfordsville', 'Southeast (Crawfordsville)'),
        ('lewis', 'Southwest (Lewis)'),
        ('nashua', 'Northeast (Nashua)'),
        ('sutherland', 'Northwest (Sutherland)')])

SDATES = OrderedDict([
        ('nov1', 'November 1'),
        ('jan1', 'January 1'),
        ('mar15', 'March 15'),
                     ])
COUNTY = {'ames': 169, 'cobs': 169, 'crawfordsville': 183, 'lewis': 155,
          'nashua': 67, 'sutherland': 141}
PDICT = {'yes': 'Colorize Labels by Corn Yield Trend',
         'no': 'No Colorize'}


def load_yields(location):
    """Loads up the county corn yields"""
    pgconn = psycopg2.connect(database='coop', host='iemdb', user='nobody')
    df = read_sql("""select year, num_value as yield
    from nass_quickstats where
    county_ansi = %s and state_alpha = 'IA' and year >= 1980
    and commodity_desc = 'CORN' and statisticcat_desc = 'YIELD'
    and unit_desc = 'BU / ACRE' ORDER by year ASC
    """, pgconn, params=(COUNTY[location],), index_col='year')
    slp, intercept, _, _, _ = stats.linregress(df.index.values,
                                               df['yield'].values)
    df['model'] = slp * df.index.values + intercept
    df['departure'] = 100. * (df['yield'] - df['model']) / df['model']
    return df


def get_description():
    """ Return a dict describing how to call this plotter """
    d = dict()
    d['description'] = """ """
    d['arguments'] = [
        dict(type='select', name='location', default='ames',
             label='Select Location:', options=STATIONS),
        dict(type='select', name='s', default='jan1',
             label='Select Plot Start Date:', options=SDATES),
        dict(type='select', name='opt', default='no',
             label='Plot Corn Yield Trends:', options=PDICT),
    ]
    return d


def load(dirname, location, sdate):
    """ Read a file please """
    data = []
    idx = []
    for line in open("%s/%s.met" % (dirname, location)):
        line = line.strip()
        if not line.startswith('19') and not line.startswith('20'):
            continue
        tokens = line.split()
        if float(tokens[5]) > 90:
            continue
        data.append(tokens)
        ts = (datetime.date(int(tokens[0]), 1, 1) +
              datetime.timedelta(days=int(tokens[1])-1))
        idx.append(ts)
    if len(data[0]) < 10:
        cols = ['year', 'doy', 'radn', 'maxt', 'mint', 'rain']
    else:
        cols = ['year', 'doy', 'radn', 'maxt', 'mint',
                'rain', 'gdd', 'st4', 'st12', 'st24',
                'st50', 'sm12', 'sm24', 'sm50']
    df = pd.DataFrame(data, index=idx,
                      columns=cols)
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if len(data[0]) < 10:
        df['gdd'] = gdd(temperature(df['maxt'].values, 'C'),
                        temperature(df['mint'].values, 'C'))
    bins = []
    today = datetime.date.today()
    for valid, _ in df.iterrows():
        if valid >= today:
            bins.append(0)
            continue
        if sdate == 'nov1' and valid.month >= 11:
            bins.append(valid.year+1)
            continue
        if valid.month < today.month:
            bins.append(valid.year)
            continue
        if valid.month == today.month and valid.day < today.day:
            bins.append(valid.year)
            continue
        bins.append(0)
    df['bin'] = bins
    df['rain'] = distance(df['rain'].values, 'MM').value('IN')
    df['avgt'] = temperature(
                    (df['maxt'] + df['mint']) / 2.0, 'C').value('F')
    return df


def plotter(fdict):
    """ Go """
    import matplotlib
    matplotlib.use('agg')
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as PathEffects
    ctx = get_autoplot_context(fdict, get_description())
    location = ctx['location']
    opt = ctx['opt']
    yields = load_yields(location)
    sdate = ctx['s']
    # we need to compute totals using two datasources
    df = load("/mesonet/share/pickup/yieldfx", location, sdate)
    cdf = load("/opt/iem/scripts/yieldfx/baseline",
               location, sdate)

    today = datetime.date.today()

    gdf = df.groupby('bin')['avgt'].mean()
    gdf2 = df.groupby('bin')['rain'].sum()
    gcdf = cdf.groupby('bin')['avgt'].mean()
    gcdf2 = cdf.groupby('bin')['rain'].sum()

    rows = []
    for year in range(1980, today.year + 1):
        if year == 1980 and sdate == 'nov1':
            continue
        if year == today.year:
            avgt = gdf[year]
            rain = gdf2[year]
        else:
            avgt = gcdf[year]
            rain = gcdf2[year]
        rows.append(dict(avgt=avgt, rain=rain, year=year))
    resdf = pd.DataFrame(rows)
    resdf.set_index('year', inplace=True)

    (fig, ax) = plt.subplots(1, 1)
    for year, row in resdf.iterrows():
        c = 'k'
        sz = 10.
        if year in yields.index and opt == 'yes':
            myyield = yields.at[year, 'departure']
            sz = 10. + (abs(int(myyield)) / 50.) * 20.
            c = 'g' if myyield > 0 else 'r'
        txt = ax.text(row['avgt'], row['rain'], "%s" % (str(year)[-2:],),
                      color=c, ha='center', va='center', zorder=4,
                      fontsize=sz)
        txt.set_path_effects([PathEffects.withStroke(linewidth=2,
                                                     foreground="w")])
    if opt == 'yes':
        for y, x in enumerate(range(-50, 51, 10)):
            if x == 0:
                continue
            sz = 10. + (abs(x) / 50.) * 20.
            c = 'g' if x > 0 else 'r'
            p = '+' if x > 0 else ''
            ax.text(1.01, float(y / 11.), "%s%s%%" % (p, x),
                    transform=ax.transAxes, color=c, fontsize=sz)
    xavg = resdf['avgt'].mean()
    ax.axvline(xavg)
    dx = (resdf['avgt'] - xavg).abs().max()
    ax.set_xlim(xavg - (dx * 1.1), xavg + (dx * 1.1))

    yavg = resdf['rain'].mean()
    ax.axhline(yavg)
    dy = (resdf['rain'] - yavg).abs().max()
    ax.set_ylim(max([0, yavg - (dy * 1.1)]), yavg + (dy * 1.1))

    sts = datetime.datetime.strptime(sdate, '%b%d')
    ax.set_title(("%s %s to %s [%s-%s]"
                  ) % (STATIONS[location],
                       sts.strftime("%-d %B"),
                       today.strftime("%-d %B"), 1980,
                       today.year))
    ax.set_xlabel("Average Temperature [$^\circ$F]")
    ax.set_ylabel("Accumulated Precipitation [inch]")
    ax.text(0.15, 0.95, "Cold & Wet", transform=ax.transAxes,
            fontsize=14, color='b', zorder=3, ha='center', va='center')
    ax.text(0.15, 0.05, "Cold & Dry", transform=ax.transAxes,
            fontsize=14, color='b', zorder=3, ha='center', va='center')
    ax.text(0.85, 0.95, "Hot & Wet", transform=ax.transAxes,
            fontsize=14, color='b', zorder=3, ha='center', va='center')
    ax.text(0.85, 0.05, "Hot & Dry", transform=ax.transAxes,
            fontsize=14, color='b', zorder=3, ha='center', va='center')
    ax.grid(True)
    ax.set_position([0.1, 0.1, 0.7, 0.8])

    return fig, resdf

if __name__ == '__main__':
    plotter(dict())
