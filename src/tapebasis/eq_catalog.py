"""Versioned catalogue of the selected official Equibles REST JSON GET routes.

Generated from the reviewed official OpenAPI schema and frozen in the package.
No schema is downloaded at runtime. Callers cannot supply arbitrary paths or
parameters. Account-owned portfolio/custom-data/tracker and binary assets are
outside this public read surface; institution backtest and direct portfolio
overlap remain MCP-only upstream and have no REST bridge here.
"""
from __future__ import annotations

import math
import re
import uuid
from datetime import datetime
from typing import Any, Mapping

#: ``family`` -> ``dataset`` -> exact documented route and filter contract.
CATALOG: dict[str, dict[str, dict[str, Any]]] = {'institutions': {'flows': {'name': 'flows',
                            'path': '/13f/flows',
                            'parameters': {'dimension': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'How to split the filers: '
                                                                        'type (default), style, '
                                                                        'turnover, horizon, aum '
                                                                        '(13F book size), client '
                                                                        '(client base), pf '
                                                                        '(private funds) or '
                                                                        'country (filer '
                                                                        'location).'},
                                           'reportDate': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'A computed quarter end '
                                                                         '(yyyy-MM-dd, defaults to '
                                                                         'the newest). Any other '
                                                                         'date returns 400 listing '
                                                                         'the computed quarters.',
                                                          'format': 'date'},
                                           'groupBy': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'none (default) or sector.'},
                                           'bucket': {'location': 'query',
                                                      'required': False,
                                                      'type': 'string',
                                                      'description': 'One bucket token of the '
                                                                     'dimension (e.g. adv or idx) '
                                                                     'to return only that '
                                                                     'bucket.'}},
                            'live': False},
                  'market_activity': {'name': 'market_activity',
                                      'path': '/13f/market-activity',
                                      'parameters': {'bucket': {'location': 'query',
                                                                'required': True,
                                                                'type': 'string',
                                                                'description': 'Required: '
                                                                               'top-buys, '
                                                                               'top-sells, '
                                                                               'new-positions or '
                                                                               'sold-out-positions.'},
                                                     'reportDate': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': '13F report '
                                                                                   'date '
                                                                                   '(yyyy-MM-dd, '
                                                                                   'defaults to '
                                                                                   'the latest '
                                                                                   'available).',
                                                                    'format': 'date'},
                                                     'limit': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': 'Maximum stocks to '
                                                                              'return (default 20, '
                                                                              'max 500).',
                                                               'default': 20,
                                                               'minimum': 1,
                                                               'maximum': 500}},
                                      'live': False},
                  'most_held': {'name': 'most_held',
                                'path': '/13f/most-held',
                                'parameters': {'reportDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': '13F report date '
                                                                             '(yyyy-MM-dd, '
                                                                             'defaults to the '
                                                                             'latest available).',
                                                              'format': 'date'},
                                               'sort': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'filers (default), '
                                                                       'filersDelta, value, '
                                                                       'conviction or crowding.',
                                                        'default': 'filers'},
                                               'limit': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Maximum stocks to return '
                                                                        '(default 25, max 500).',
                                                         'default': 25,
                                                         'minimum': 1,
                                                         'maximum': 500}},
                                'live': False},
                  'consensus_holdings': {'name': 'consensus_holdings',
                                         'path': '/consensus-holdings',
                                         'parameters': {'institutions': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'string',
                                                                         'description': 'Comma- or '
                                                                                        'semicolon-separated '
                                                                                        'institution '
                                                                                        'names or '
                                                                                        'CIKs. '
                                                                                        'Exact '
                                                                                        'names, '
                                                                                        'exact '
                                                                                        'CIKs and '
                                                                                        'verified '
                                                                                        'aliases '
                                                                                        'resolve; '
                                                                                        'a unique '
                                                                                        'partial '
                                                                                        'name '
                                                                                        'resolves, '
                                                                                        'while an '
                                                                                        'ambiguous '
                                                                                        'partial '
                                                                                        'returns '
                                                                                        '400 with '
                                                                                        'candidate '
                                                                                        'CIKs and '
                                                                                        'latest-quarter '
                                                                                        'context. '
                                                                                        '2-25 '
                                                                                        'distinct '
                                                                                        'institutions.'},
                                                        'reportDate': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': '13F report '
                                                                                      'date '
                                                                                      '(yyyy-MM-dd, '
                                                                                      'defaults to '
                                                                                      'the latest '
                                                                                      'common '
                                                                                      'quarter). '
                                                                                      'Must be a '
                                                                                      'report date '
                                                                                      'all '
                                                                                      'resolved '
                                                                                      'funds share '
                                                                                      '; any other '
                                                                                      'date '
                                                                                      'returns 400 '
                                                                                      'listing the '
                                                                                      'shared '
                                                                                      'dates.',
                                                                       'format': 'date'},
                                                        'minFunds': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Minimum '
                                                                                    'number of '
                                                                                    'funds a stock '
                                                                                    'must be held '
                                                                                    'by to appear '
                                                                                    '(default 1 ; '
                                                                                    'note that 1 '
                                                                                    'also includes '
                                                                                    'stocks held '
                                                                                    'by a single '
                                                                                    'fund; set 2 '
                                                                                    'or more for '
                                                                                    'true '
                                                                                    'consensus).',
                                                                     'default': 1},
                                                        'limit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Maximum stocks '
                                                                                 'to return '
                                                                                 '(default 30, max '
                                                                                 '500).',
                                                                  'minimum': 1,
                                                                  'maximum': 500}},
                                         'live': False},
                  'institutions': {'name': 'institutions',
                                   'path': '/institutions',
                                   'parameters': {'query': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Institution name, '
                                                                           'partial name, or CIK '
                                                                           '(required).'},
                                                  'limit': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Maximum results to '
                                                                           'return (default 10, '
                                                                           'max 500).',
                                                            'default': 10,
                                                            'minimum': 1,
                                                            'maximum': 500},
                                                  'holderTypes': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Comma-separated '
                                                                                 'holder type '
                                                                                 'tokens to keep: '
                                                                                 'adv, era, ia, '
                                                                                 'bank, ins, bd, '
                                                                                 'fund, plan, '
                                                                                 'nonus, hc, unk '
                                                                                 '(unk also '
                                                                                 'matches a filer '
                                                                                 'not yet '
                                                                                 'classified).'}},
                                   'live': False},
                  'institution_activity': {'name': 'institution_activity',
                                           'path': '/institutions/{cik}/activity',
                                           'parameters': {'cik': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'SEC CIK of the '
                                                                                 'institution (see '
                                                                                 'GET '
                                                                                 'v1/institutions).'},
                                                          'reportDate': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'string',
                                                                         'description': '13F '
                                                                                        'report '
                                                                                        'date '
                                                                                        '(yyyy-MM-dd, '
                                                                                        'defaults '
                                                                                        'to the '
                                                                                        "institution's "
                                                                                        'latest). '
                                                                                        'Must be '
                                                                                        'one the '
                                                                                        'institution '
                                                                                        'reported '
                                                                                        '; any '
                                                                                        'other '
                                                                                        'date '
                                                                                        'returns '
                                                                                        '400 '
                                                                                        'listing '
                                                                                        'the '
                                                                                        'available '
                                                                                        'dates.',
                                                                         'format': 'date'},
                                                          'bucket': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'string',
                                                                     'description': 'Optional '
                                                                                    'filter: '
                                                                                    'initiated, '
                                                                                    'increased, '
                                                                                    'reduced or '
                                                                                    'exited.'},
                                                          'limit': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Maximum stocks '
                                                                                   'to return per '
                                                                                   'bucket '
                                                                                   '(default 20, '
                                                                                   'max 500).',
                                                                    'default': 20,
                                                                    'minimum': 1,
                                                                    'maximum': 500}},
                                           'live': False},
                  'institution_beneficial_ownership': {'name': 'institution_beneficial_ownership',
                                                       'path': '/institutions/{cik}/beneficial-ownership',
                                                       'parameters': {'cik': {'location': 'path',
                                                                              'required': True,
                                                                              'type': 'string',
                                                                              'description': 'SEC '
                                                                                             'CIK '
                                                                                             'of '
                                                                                             'the '
                                                                                             'institution '
                                                                                             '(see '
                                                                                             'GET '
                                                                                             'v1/institutions).'},
                                                                      'view': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'string',
                                                                               'description': 'default '
                                                                                              '(current '
                                                                                              'and '
                                                                                              'unconfirmed '
                                                                                              'stakes) '
                                                                                              'or '
                                                                                              'all '
                                                                                              '(every '
                                                                                              'stake, '
                                                                                              'including '
                                                                                              'those '
                                                                                              'reported '
                                                                                              'below '
                                                                                              '5%, '
                                                                                              'exited, '
                                                                                              'or '
                                                                                              'on '
                                                                                              'a '
                                                                                              'security '
                                                                                              'that '
                                                                                              'no '
                                                                                              'longer '
                                                                                              'trades).',
                                                                               'default': 'default'},
                                                                      'limit': {'location': 'query',
                                                                                'required': False,
                                                                                'type': 'integer',
                                                                                'description': 'Maximum '
                                                                                               'rows '
                                                                                               'to '
                                                                                               'return '
                                                                                               '(1–500; '
                                                                                               'default '
                                                                                               'varies '
                                                                                               'per '
                                                                                               'endpoint).',
                                                                                'minimum': 1,
                                                                                'maximum': 500},
                                                                      'offset': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'integer',
                                                                                 'description': 'Rows '
                                                                                                'to '
                                                                                                'skip '
                                                                                                'before '
                                                                                                'the '
                                                                                                'first '
                                                                                                'returned '
                                                                                                'row '
                                                                                                '(default '
                                                                                                '0).'}},
                                                       'live': False},
                  'institution_portfolio': {'name': 'institution_portfolio',
                                            'path': '/institutions/{cik}/portfolio',
                                            'parameters': {'cik': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': 'SEC CIK of the '
                                                                                  'institution '
                                                                                  '(see GET '
                                                                                  'v1/institutions).'},
                                                           'reportDate': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': '13F '
                                                                                         'report '
                                                                                         'date '
                                                                                         '(yyyy-MM-dd, '
                                                                                         'defaults '
                                                                                         'to the '
                                                                                         "institution's "
                                                                                         'latest). '
                                                                                         'Must be '
                                                                                         'one the '
                                                                                         'institution '
                                                                                         'reported '
                                                                                         '; any '
                                                                                         'other '
                                                                                         'date '
                                                                                         'returns '
                                                                                         '400 '
                                                                                         'listing '
                                                                                         'the '
                                                                                         'available '
                                                                                         'dates.',
                                                                          'format': 'date'},
                                                           'limit': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Maximum rows '
                                                                                    'to return '
                                                                                    '(1–500; '
                                                                                    'default '
                                                                                    'varies per '
                                                                                    'endpoint).',
                                                                     'minimum': 1,
                                                                     'maximum': 500},
                                                           'offset': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': 'Rows to skip '
                                                                                     'before the '
                                                                                     'first '
                                                                                     'returned row '
                                                                                     '(default '
                                                                                     '0).'}},
                                            'live': False},
                  'institution_profile': {'name': 'institution_profile',
                                          'path': '/institutions/{cik}/profile',
                                          'parameters': {'cik': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'SEC CIK of the '
                                                                                'institution (see '
                                                                                'GET '
                                                                                'v1/institutions).'}},
                                          'live': False},
                  'institution_sector_allocation': {'name': 'institution_sector_allocation',
                                                    'path': '/institutions/{cik}/sector-allocation',
                                                    'parameters': {'cik': {'location': 'path',
                                                                           'required': True,
                                                                           'type': 'string',
                                                                           'description': 'SEC CIK '
                                                                                          'of the '
                                                                                          'institution '
                                                                                          '(see '
                                                                                          'GET '
                                                                                          'v1/institutions).'},
                                                                   'reportDate': {'location': 'query',
                                                                                  'required': False,
                                                                                  'type': 'string',
                                                                                  'description': '13F '
                                                                                                 'report '
                                                                                                 'date '
                                                                                                 '(yyyy-MM-dd, '
                                                                                                 'defaults '
                                                                                                 'to '
                                                                                                 'the '
                                                                                                 "institution's "
                                                                                                 'latest). '
                                                                                                 'Must '
                                                                                                 'be '
                                                                                                 'one '
                                                                                                 'the '
                                                                                                 'institution '
                                                                                                 'reported '
                                                                                                 '; '
                                                                                                 'any '
                                                                                                 'other '
                                                                                                 'date '
                                                                                                 'returns '
                                                                                                 '400 '
                                                                                                 'listing '
                                                                                                 'the '
                                                                                                 'available '
                                                                                                 'dates.',
                                                                                  'format': 'date'},
                                                                   'groupBy': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'string',
                                                                               'description': 'Grouping '
                                                                                              'level: '
                                                                                              'industry '
                                                                                              '(default) '
                                                                                              'or '
                                                                                              'sector.',
                                                                               'default': 'industry'}},
                                                    'live': False},
                  'institution_style_history': {'name': 'institution_style_history',
                                                'path': '/institutions/{cik}/style-history',
                                                'parameters': {'cik': {'location': 'path',
                                                                       'required': True,
                                                                       'type': 'string',
                                                                       'description': 'SEC CIK of '
                                                                                      'the '
                                                                                      'institution '
                                                                                      '(see GET '
                                                                                      'v1/institutions).'},
                                                               'limit': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Measured '
                                                                                        'quarters '
                                                                                        'to '
                                                                                        'return, '
                                                                                        'newest '
                                                                                        'first '
                                                                                        '(default '
                                                                                        '8, max '
                                                                                        '40).',
                                                                         'default': 8,
                                                                         'minimum': 1,
                                                                         'maximum': 40}},
                                                'live': False},
                  'institution_summary': {'name': 'institution_summary',
                                          'path': '/institutions/{cik}/summary',
                                          'parameters': {'cik': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'SEC CIK of the '
                                                                                'institution (see '
                                                                                'GET '
                                                                                'v1/institutions).'},
                                                         'reportDate': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': '13F report '
                                                                                       'date '
                                                                                       '(yyyy-MM-dd, '
                                                                                       'defaults '
                                                                                       'to the '
                                                                                       "institution's "
                                                                                       'latest). '
                                                                                       'Must be '
                                                                                       'one the '
                                                                                       'institution '
                                                                                       'reported ; '
                                                                                       'any other '
                                                                                       'date '
                                                                                       'returns '
                                                                                       '400 '
                                                                                       'listing '
                                                                                       'the '
                                                                                       'available '
                                                                                       'dates.',
                                                                        'format': 'date'}},
                                          'live': False},
                  'super_investors': {'name': 'super_investors',
                                      'path': '/super-investors',
                                      'parameters': {},
                                      'live': False}},
 'macro': {'cftc_contracts': {'name': 'cftc_contracts',
                              'path': '/cftc/contracts',
                              'parameters': {'query': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Market code, verified '
                                                                      'futures alias, or search '
                                                                      'words (e.g. 088691, GC, '
                                                                      'gold futures, crude oil). '
                                                                      'Omit to list every tracked '
                                                                      'contract.'},
                                             'limit': {'location': 'query',
                                                       'required': False,
                                                       'type': 'integer',
                                                       'description': 'Maximum results (default '
                                                                      '50, max 500).',
                                                       'minimum': 1,
                                                       'maximum': 500}},
                              'live': False},
           'cftc_positions': {'name': 'cftc_positions',
                              'path': '/cftc/contracts/{marketCode}/positions',
                              'parameters': {'marketCode': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'CFTC contract market '
                                                                           'code (e.g. 067651 for '
                                                                           'Crude Oil, 088691 for '
                                                                           'Gold).'},
                                             'startDate': {'location': 'query',
                                                           'required': False,
                                                           'type': 'string',
                                                           'description': 'Start report date '
                                                                          '(yyyy-MM-dd, defaults '
                                                                          'to 1 year ago).',
                                                           'format': 'date'},
                                             'endDate': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'End report date '
                                                                        '(yyyy-MM-dd, defaults to '
                                                                        'today).',
                                                         'format': 'date'},
                                             'limit': {'location': 'query',
                                                       'required': False,
                                                       'type': 'integer',
                                                       'description': 'Maximum rows to return '
                                                                      '(1–500; default varies per '
                                                                      'endpoint).',
                                                       'minimum': 1,
                                                       'maximum': 500},
                                             'offset': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Rows to skip before the '
                                                                       'first returned row '
                                                                       '(default 0).'}},
                              'live': False},
           'cftc_positions_latest': {'name': 'cftc_positions_latest',
                                     'path': '/cftc/positions/latest',
                                     'parameters': {'category': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Category filter: '
                                                                                'Agriculture, '
                                                                                'Energy, Metals, '
                                                                                'EquityIndices, '
                                                                                'InterestRates, '
                                                                                'Currencies '
                                                                                '(defaults to '
                                                                                'all).'}},
                                     'live': False},
           'economic_calendar': {'name': 'economic_calendar',
                                 'path': '/fred/calendar',
                                 'parameters': {'startDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Start date '
                                                                             '(yyyy-MM-dd, '
                                                                             'defaults to today).',
                                                              'format': 'date'},
                                                'endDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'End date (yyyy-MM-dd, '
                                                                           'defaults to 30 days '
                                                                           'after the start date).',
                                                            'format': 'date'},
                                                'minImportance': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Minimum '
                                                                                 'importance tier '
                                                                                 'to include: low, '
                                                                                 'medium, or high '
                                                                                 '(defaults to low '
                                                                                 '= everything).'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum release dates to '
                                                                         'return (default 100, max '
                                                                         '500).',
                                                          'minimum': 1,
                                                          'maximum': 500},
                                                'country': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Market country code, '
                                                                           'US or CA (defaults to '
                                                                           'every market).'}},
                                 'live': False},
           'fred_latest': {'name': 'fred_latest',
                           'path': '/fred/latest',
                           'parameters': {'category': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Category filter: '
                                                                      'InterestRates, '
                                                                      'YieldSpreads, '
                                                                      'CorporateBondSpreads, '
                                                                      'Inflation, Employment, '
                                                                      'GdpAndOutput, MoneySupply, '
                                                                      'Sentiment, Housing, '
                                                                      'ExchangeRates, Market '
                                                                      '(defaults to all).'},
                                          'country': {'location': 'query',
                                                      'required': False,
                                                      'type': 'string',
                                                      'description': 'Country as an ISO code: US '
                                                                     '(default) or CA. One '
                                                                     'response never mixes two '
                                                                     "countries' series.",
                                                      'default': 'US'}},
                           'live': False},
           'fred_series': {'name': 'fred_series',
                           'path': '/fred/series',
                           'parameters': {'query': {'location': 'query',
                                                    'required': True,
                                                    'type': 'string',
                                                    'description': 'Series id, standard alias, or '
                                                                   'search words (e.g. FEDFUNDS, '
                                                                   'fed funds rate, jobless '
                                                                   'claims, inflation). Required.'},
                                          'limit': {'location': 'query',
                                                    'required': False,
                                                    'type': 'integer',
                                                    'description': 'Maximum results (default 20, '
                                                                   'max 500).',
                                                    'minimum': 1,
                                                    'maximum': 500}},
                           'live': False},
           'fred_observations': {'name': 'fred_observations',
                                 'path': '/fred/series/{seriesId}/observations',
                                 'parameters': {'seriesId': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'FRED series id (e.g. '
                                                                            'FEDFUNDS, CPIAUCSL, '
                                                                            'UNRATE, GDP, T10Y2Y, '
                                                                            'VIXCLS).'},
                                                'startDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Start date '
                                                                             '(yyyy-MM-dd, '
                                                                             'defaults to 1 year '
                                                                             'ago).',
                                                              'format': 'date'},
                                                'endDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'End date (yyyy-MM-dd, '
                                                                           'defaults to today).',
                                                            'format': 'date'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum rows to return '
                                                                         '(1–500; default varies '
                                                                         'per endpoint).',
                                                          'minimum': 1,
                                                          'maximum': 500},
                                                'offset': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Rows to skip before the '
                                                                          'first returned row '
                                                                          '(default 0).'}},
                                 'live': False}},
 'public_policy': {'congress_market_activity': {'name': 'congress_market_activity',
                                                'path': '/congress/market-activity',
                                                'parameters': {'days': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': 'Trailing '
                                                                                       'disclosure '
                                                                                       'window in '
                                                                                       'days '
                                                                                       '(default '
                                                                                       '30, max '
                                                                                       '365; '
                                                                                       'values '
                                                                                       'outside '
                                                                                       'the range '
                                                                                       'are '
                                                                                       'clamped ; '
                                                                                       'the '
                                                                                       'response '
                                                                                       'echoes the '
                                                                                       'applied '
                                                                                       'window).',
                                                                        'maximum': 365},
                                                               'direction': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'string',
                                                                             'description': 'Ranking '
                                                                                            'direction: '
                                                                                            'buys '
                                                                                            '(most '
                                                                                            'net '
                                                                                            'congressional '
                                                                                            'buying '
                                                                                            'first, '
                                                                                            'default) '
                                                                                            'or '
                                                                                            'sells '
                                                                                            '(most '
                                                                                            'net '
                                                                                            'selling '
                                                                                            'first).'},
                                                               'chamber': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'string',
                                                                           'description': 'Filter '
                                                                                          'by '
                                                                                          'chamber: '
                                                                                          'senate '
                                                                                          'or '
                                                                                          'house '
                                                                                          '(defaults '
                                                                                          'to '
                                                                                          'both).'},
                                                               'limit': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Maximum '
                                                                                        'stocks to '
                                                                                        'return '
                                                                                        '(default '
                                                                                        '25, max '
                                                                                        '500).',
                                                                         'minimum': 1,
                                                                         'maximum': 500}},
                                                'live': False},
                   'congress_members': {'name': 'congress_members',
                                        'path': '/congress/members',
                                        'parameters': {'query': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Search query ; '
                                                                                'name words or '
                                                                                'verified alias '
                                                                                '(e.g. Pelosi, '
                                                                                'Cruz, Dan '
                                                                                'Crenshaw).'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum results '
                                                                                '(default 20, max '
                                                                                '500; zero or '
                                                                                'negative values '
                                                                                'are rejected, '
                                                                                'values above the '
                                                                                'maximum are '
                                                                                'clamped).',
                                                                 'minimum': 1,
                                                                 'maximum': 500},
                                                       'position': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'Optional '
                                                                                   'position '
                                                                                   'filter: '
                                                                                   'Senator or '
                                                                                   'Representative. '
                                                                                   'Senate and '
                                                                                   'House are '
                                                                                   'accepted '
                                                                                   'aliases.'}},
                                        'live': False},
                   'congress_net_worth': {'name': 'congress_net_worth',
                                          'path': '/congress/members/{id}/net-worth',
                                          'parameters': {'id': {'location': 'path',
                                                                'required': True,
                                                                'type': 'string',
                                                                'description': 'Congress member id '
                                                                               '(from '
                                                                               '/v1/congress/members).',
                                                                'format': 'uuid'},
                                                         'limit': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Maximum years '
                                                                                  'to return '
                                                                                  '(default 20, '
                                                                                  'max 500).',
                                                                   'minimum': 1,
                                                                   'maximum': 500}},
                                          'live': False},
                   'congress_trades': {'name': 'congress_trades',
                                       'path': '/congress/trades',
                                       'parameters': {'ticker': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Listed security '
                                                                                'ticker (e.g. AAPL '
                                                                                'or VOO).'},
                                                      'memberId': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Congress member '
                                                                                  'id (from '
                                                                                  '/v1/congress/members).',
                                                                   'format': 'uuid'},
                                                      'transactionType': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': 'Filter '
                                                                                         'by '
                                                                                         'transaction '
                                                                                         'type: '
                                                                                         'Purchase '
                                                                                         'or Sale '
                                                                                         '(defaults '
                                                                                         'to '
                                                                                         'all).'},
                                                      'startDate': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'Start '
                                                                                   'transaction '
                                                                                   'date '
                                                                                   '(yyyy-MM-dd, '
                                                                                   'defaults to 1 '
                                                                                   'year ago).',
                                                                    'format': 'date'},
                                                      'endDate': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'End transaction '
                                                                                 'date '
                                                                                 '(yyyy-MM-dd, '
                                                                                 'defaults to '
                                                                                 'today).',
                                                                  'format': 'date'},
                                                      'limit': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Maximum rows to '
                                                                               'return (1–500; '
                                                                               'default varies per '
                                                                               'endpoint).',
                                                                'minimum': 1,
                                                                'maximum': 500},
                                                      'offset': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Rows to skip '
                                                                                'before the first '
                                                                                'returned row '
                                                                                '(default 0).'}},
                                       'live': False},
                   'government_contracts': {'name': 'government_contracts',
                                            'path': '/government-contracts/top',
                                            'parameters': {'startDate': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'string',
                                                                         'description': 'Start '
                                                                                        'action '
                                                                                        'date '
                                                                                        '(yyyy-MM-dd, '
                                                                                        'defaults '
                                                                                        'to 1 year '
                                                                                        'ago).',
                                                                         'format': 'date'},
                                                           'endDate': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'End action '
                                                                                      'date '
                                                                                      '(yyyy-MM-dd, '
                                                                                      'defaults to '
                                                                                      'today).',
                                                                       'format': 'date'},
                                                           'limit': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Maximum '
                                                                                    'companies to '
                                                                                    'return '
                                                                                    '(default 25, '
                                                                                    'max 500).',
                                                                     'minimum': 1,
                                                                     'maximum': 500},
                                                           'country': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'Awarding '
                                                                                      'government: '
                                                                                      'US '
                                                                                      '(default) '
                                                                                      'or CA.',
                                                                       'default': 'US'}},
                                            'live': False},
                   'company_government_contracts': {'name': 'company_government_contracts',
                                                    'path': '/stocks/{ticker}/government-contracts',
                                                    'parameters': {'ticker': {'location': 'path',
                                                                              'required': True,
                                                                              'type': 'string',
                                                                              'description': 'Stock '
                                                                                             'ticker '
                                                                                             'symbol '
                                                                                             '(e.g. '
                                                                                             'LMT, '
                                                                                             'RTX, '
                                                                                             'BA). '
                                                                                             'Class '
                                                                                             'shares '
                                                                                             'use '
                                                                                             'a '
                                                                                             'dash '
                                                                                             '(BRK-B); '
                                                                                             'the '
                                                                                             'dot '
                                                                                             'form '
                                                                                             '(BRK.B) '
                                                                                             'is '
                                                                                             'also '
                                                                                             'accepted.'},
                                                                   'startDate': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'string',
                                                                                 'description': 'Start '
                                                                                                'action '
                                                                                                'date '
                                                                                                '(yyyy-MM-dd, '
                                                                                                'defaults '
                                                                                                'to '
                                                                                                '1 '
                                                                                                'year '
                                                                                                'ago).',
                                                                                 'format': 'date'},
                                                                   'endDate': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'string',
                                                                               'description': 'End '
                                                                                              'action '
                                                                                              'date '
                                                                                              '(yyyy-MM-dd, '
                                                                                              'defaults '
                                                                                              'to '
                                                                                              'today).',
                                                                               'format': 'date'},
                                                                   'limit': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'integer',
                                                                             'description': 'Maximum '
                                                                                            'rows '
                                                                                            'to '
                                                                                            'return '
                                                                                            '(1–500; '
                                                                                            'default '
                                                                                            'varies '
                                                                                            'per '
                                                                                            'endpoint).',
                                                                             'minimum': 1,
                                                                             'maximum': 500},
                                                                   'offset': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'integer',
                                                                              'description': 'Rows '
                                                                                             'to '
                                                                                             'skip '
                                                                                             'before '
                                                                                             'the '
                                                                                             'first '
                                                                                             'returned '
                                                                                             'row '
                                                                                             '(default '
                                                                                             '0).'},
                                                                   'agency': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'string',
                                                                              'description': 'Optional '
                                                                                             'case-insensitive '
                                                                                             'substring '
                                                                                             'filter '
                                                                                             'on '
                                                                                             'awarding '
                                                                                             'agency.'},
                                                                   'sortBy': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'string',
                                                                              'description': 'Sort '
                                                                                             'by '
                                                                                             'amount '
                                                                                             '(default) '
                                                                                             'or '
                                                                                             'date.',
                                                                              'default': 'amount'},
                                                                   'country': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'string',
                                                                               'description': 'Awarding '
                                                                                              'government: '
                                                                                              'US '
                                                                                              '(default) '
                                                                                              'or '
                                                                                              'CA.'}},
                                                    'live': False}},
 'crypto': {'crypto_directory': {'name': 'crypto_directory',
                                 'path': '/crypto',
                                 'parameters': {'query': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Keep the coins whose '
                                                                         'symbol starts with this '
                                                                         '(e.g. BT); letters and '
                                                                         'digits only.'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum rows to return '
                                                                         '(1–500; default varies '
                                                                         'per endpoint).',
                                                          'minimum': 1,
                                                          'maximum': 500},
                                                'offset': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Rows to skip before the '
                                                                          'first returned row '
                                                                          '(default 0).'}},
                                 'live': False},
            'crypto_quotes': {'name': 'crypto_quotes',
                              'path': '/crypto/quotes',
                              'parameters': {'symbols': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'Comma-separated coin '
                                                                        'symbols (e.g. '
                                                                        'BTC,ETH,SOL), max 25; '
                                                                        'BTC/USD and BTC-USD also '
                                                                        'work.'}},
                              'live': False},
            'crypto_bars': {'name': 'crypto_bars',
                            'path': '/crypto/{symbol}/bars',
                            'parameters': {'symbol': {'location': 'path',
                                                      'required': True,
                                                      'type': 'string',
                                                      'description': 'Coin symbol (e.g. BTC) or '
                                                                     'its pair with a dash '
                                                                     '(BTC-USD); GET /v1/crypto '
                                                                     'lists them.'},
                                           'interval': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'Candle size: a whole '
                                                                       'number of minutes from '
                                                                       '1min (default) to 240min, '
                                                                       'such as 5min or 15min, or '
                                                                       'of hours from 1hour to '
                                                                       '4hour.'},
                                           'startDate': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'First UTC day, YYYY-MM-DD '
                                                                        '(default: 7 days before '
                                                                        'the end, 30 for hourly '
                                                                        'intervals).',
                                                         'format': 'date'},
                                           'endDate': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Last UTC day, YYYY-MM-DD '
                                                                      '(default: now).',
                                                       'format': 'date'},
                                           'endTime': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Return only candles that '
                                                                      'start before this RFC 3339 '
                                                                      'time; replaces endDate. '
                                                                      "Pass the oldest candle's "
                                                                      'time to continue a '
                                                                      'truncated read, and keep '
                                                                      'startDate: without it the '
                                                                      'window slides.',
                                                       'format': 'timestamp'},
                                           'limit': {'location': 'query',
                                                     'required': False,
                                                     'type': 'integer',
                                                     'description': 'Maximum candles to return, '
                                                                    'newest first (default: 250, '
                                                                    'max: 500).',
                                                     'minimum': 1,
                                                     'maximum': 500}},
                            'live': False},
            'crypto_price_history': {'name': 'crypto_price_history',
                                     'path': '/crypto/{symbol}/prices',
                                     'parameters': {'symbol': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Coin symbol (e.g. '
                                                                              'BTC) or its pair '
                                                                              'with a dash '
                                                                              '(BTC-USD); GET '
                                                                              '/v1/crypto lists '
                                                                              'them.'},
                                                    'startDate': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'First UTC day, '
                                                                                 'YYYY-MM-DD '
                                                                                 '(default: the '
                                                                                 "coin's first "
                                                                                 'trade).',
                                                                  'format': 'date'},
                                                    'endDate': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'Last UTC day, '
                                                                               'YYYY-MM-DD '
                                                                               '(default: today). '
                                                                               'To continue a '
                                                                               'truncated answer, '
                                                                               'pass the day '
                                                                               'before its oldest '
                                                                               'candle.',
                                                                'format': 'date'},
                                                    'limit': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Maximum days to '
                                                                             'return, newest first '
                                                                             '(default: 250, max: '
                                                                             '500).',
                                                              'minimum': 1,
                                                              'maximum': 500}},
                                     'live': False},
            'crypto_quote': {'name': 'crypto_quote',
                             'path': '/crypto/{symbol}/quote',
                             'parameters': {'symbol': {'location': 'path',
                                                       'required': True,
                                                       'type': 'string',
                                                       'description': 'Coin symbol (e.g. BTC) or '
                                                                      'its pair with a dash '
                                                                      '(BTC-USD); GET /v1/crypto '
                                                                      "lists them. A coin's symbol "
                                                                      'is not a stock ticker: '
                                                                      '/v1/crypto/BTC/quote is '
                                                                      'Bitcoin.'}},
                             'live': False}},
 'funds': {'etf_directory': {'name': 'etf_directory',
                             'path': '/etfs',
                             'parameters': {'query': {'location': 'query',
                                                      'required': True,
                                                      'type': 'string',
                                                      'description': 'Ticker, fund name, sponsor '
                                                                     'or ISIN to search for (for '
                                                                     'example SPY, S&P 500, '
                                                                     'iShares, SXR8 or '
                                                                     'IE00B5BMR087); required.'},
                                            'exchange': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'Market identifier code of '
                                                                        'one exchange outside the '
                                                                        'US to search alone (for '
                                                                        'example XETR); GET '
                                                                        '/v1/markets lists the '
                                                                        'codes.'},
                                            'limit': {'location': 'query',
                                                      'required': False,
                                                      'type': 'integer',
                                                      'description': 'Maximum results to return '
                                                                     '(default 20, max 500).',
                                                      'minimum': 1,
                                                      'maximum': 500}},
                             'live': False},
           'etf_profile': {'name': 'etf_profile',
                           'path': '/etfs/{ticker}',
                           'parameters': {'ticker': {'location': 'path',
                                                     'required': True,
                                                     'type': 'string',
                                                     'description': 'Exact exchange-traded ticker '
                                                                    '(for example SPY, VOO, or '
                                                                    'IVV), or MIC:TICKER for a '
                                                                    'fund listed on another '
                                                                    'exchange (for example '
                                                                    'XETR:SXR8), whose figures are '
                                                                    'in its trading currency.'}},
                           'live': False},
           'etf_holdings': {'name': 'etf_holdings',
                            'path': '/etfs/{ticker}/holdings',
                            'parameters': {'ticker': {'location': 'path',
                                                      'required': True,
                                                      'type': 'string',
                                                      'description': 'Exact exchange-traded ticker '
                                                                     '(for example SPY).'},
                                           'limit': {'location': 'query',
                                                     'required': False,
                                                     'type': 'integer',
                                                     'description': 'Maximum rows to return '
                                                                    '(1–500; default varies per '
                                                                    'endpoint).',
                                                     'minimum': 1,
                                                     'maximum': 500},
                                           'offset': {'location': 'query',
                                                      'required': False,
                                                      'type': 'integer',
                                                      'description': 'Rows to skip before the '
                                                                     'first returned row (default '
                                                                     '0).'}},
                            'live': False},
           'fund_directory': {'name': 'fund_directory',
                              'path': '/funds',
                              'parameters': {'query': {'location': 'query',
                                                       'required': True,
                                                       'type': 'string',
                                                       'description': 'Fund name, ticker, '
                                                                      'profileId, series id, '
                                                                      'registrant, or verified '
                                                                      'share-class alias to search '
                                                                      "for (e.g. 'Russell 2000', "
                                                                      "'iShares', 'IWM', 'VFIAX'); "
                                                                      'required.'},
                                             'limit': {'location': 'query',
                                                       'required': False,
                                                       'type': 'integer',
                                                       'description': 'Maximum funds to return '
                                                                      '(default 20, max 500; zero '
                                                                      'or negative values are '
                                                                      'rejected, values above the '
                                                                      'maximum are clamped).',
                                                       'minimum': 1,
                                                       'maximum': 500}},
                              'live': False},
           'fund_holdings': {'name': 'fund_holdings',
                             'path': '/funds/{ticker}/holdings',
                             'parameters': {'ticker': {'location': 'path',
                                                       'required': True,
                                                       'type': 'string',
                                                       'description': 'Fund ticker, profileId, SEC '
                                                                      'series id, or verified '
                                                                      'share-class alias (e.g. '
                                                                      'SPY, '
                                                                      "'vanguard-500-index-fund-s000002839', "
                                                                      'S000002839, or VOO).'},
                                            'limit': {'location': 'query',
                                                      'required': False,
                                                      'type': 'integer',
                                                      'description': 'Maximum rows to return '
                                                                     '(1–500; default varies per '
                                                                     'endpoint).',
                                                      'minimum': 1,
                                                      'maximum': 500},
                                            'offset': {'location': 'query',
                                                       'required': False,
                                                       'type': 'integer',
                                                       'description': 'Rows to skip before the '
                                                                      'first returned row (default '
                                                                      '0).'}},
                             'live': False},
           'fund_operations': {'name': 'fund_operations',
                               'path': '/funds/{ticker}/operations',
                               'parameters': {'ticker': {'location': 'path',
                                                         'required': True,
                                                         'type': 'string',
                                                         'description': 'Fund ticker, profileId, '
                                                                        'SEC series id, or '
                                                                        'verified share-class '
                                                                        'alias (e.g. MXF, IVV, '
                                                                        'S000004310, or VOO).'},
                                              'limit': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Maximum annual reports to '
                                                                       'return (default 10, max '
                                                                       '500; zero or negative '
                                                                       'values are rejected, '
                                                                       'values above the maximum '
                                                                       'are clamped).',
                                                        'minimum': 1,
                                                        'maximum': 500}},
                               'live': False}},
 'market_context': {'fda_catalysts': {'name': 'fda_catalysts',
                                      'path': '/fda/catalysts',
                                      'parameters': {'startDate': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Start date '
                                                                                  '(yyyy-MM-dd, '
                                                                                  'defaults to '
                                                                                  'today).',
                                                                   'format': 'date'},
                                                     'endDate': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'End date '
                                                                                '(yyyy-MM-dd, '
                                                                                'defaults to 90 '
                                                                                'days after the '
                                                                                'start; floored at '
                                                                                'the start date).',
                                                                 'format': 'date'},
                                                     'limit': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': 'Maximum meetings to '
                                                                              'return (default 60, '
                                                                              'max 500).',
                                                               'minimum': 1,
                                                               'maximum': 500}},
                                      'live': False},
                    'index_directory': {'name': 'index_directory',
                                        'path': '/indexes',
                                        'parameters': {},
                                        'live': False},
                    'index_profile': {'name': 'index_profile',
                                      'path': '/indexes/{index}',
                                      'parameters': {'index': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Index slug or name: '
                                                                              '"sp-500", "S&P '
                                                                              '500", "nasdaq-100", '
                                                                              '"Russell 2000".'},
                                                     'limit': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': 'Maximum rows to '
                                                                              'return (1–500; '
                                                                              'default varies per '
                                                                              'endpoint).',
                                                               'minimum': 1,
                                                               'maximum': 500},
                                                     'offset': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Rows to skip '
                                                                               'before the first '
                                                                               'returned row '
                                                                               '(default 0).'}},
                                      'live': False},
                    'index_changes': {'name': 'index_changes',
                                      'path': '/indexes/{index}/changes',
                                      'parameters': {'index': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Index slug or name: '
                                                                              '"sp-500", "S&P '
                                                                              '500", "nasdaq-100", '
                                                                              '"Russell 2000".'},
                                                     'limit': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': 'Maximum rows to '
                                                                              'return (1–500; '
                                                                              'default varies per '
                                                                              'endpoint).',
                                                               'minimum': 1,
                                                               'maximum': 500},
                                                     'offset': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Rows to skip '
                                                                               'before the first '
                                                                               'returned row '
                                                                               '(default 0).'}},
                                      'live': False},
                    'index_forecast': {'name': 'index_forecast',
                                       'path': '/indexes/{index}/forecast',
                                       'parameters': {'index': {'location': 'path',
                                                                'required': True,
                                                                'type': 'string',
                                                                'description': 'Index slug or '
                                                                               'name. The Dow '
                                                                               'publishes no '
                                                                               'quantitative entry '
                                                                               'rule and returns '
                                                                               '404.'}},
                                       'live': False},
                    'index_fund_flows': {'name': 'index_fund_flows',
                                         'path': '/indexes/{index}/fund-flows',
                                         'parameters': {'index': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Index slug or '
                                                                                 'name: "sp-500", '
                                                                                 '"S&P 500", '
                                                                                 '"Russell 2000". '
                                                                                 'An index with no '
                                                                                 'tracking fund '
                                                                                 'whose daily '
                                                                                 'holdings file is '
                                                                                 'read returns '
                                                                                 '404.'}},
                                         'live': False},
                    'insider_sentiment_scores': {'name': 'insider_sentiment_scores',
                                                 'path': '/insider-sentiment-scores',
                                                 'parameters': {'clusterBuysOnly': {'location': 'query',
                                                                                    'required': False,
                                                                                    'type': 'boolean',
                                                                                    'description': 'Return '
                                                                                                   'only '
                                                                                                   'cluster '
                                                                                                   'buys '
                                                                                                   '(three '
                                                                                                   'or '
                                                                                                   'more '
                                                                                                   'distinct '
                                                                                                   'insiders '
                                                                                                   'buying '
                                                                                                   'in '
                                                                                                   'the '
                                                                                                   'window).',
                                                                                    'default': False},
                                                                'minMarketCap': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'number',
                                                                                 'description': 'Minimum '
                                                                                                'market '
                                                                                                'capitalization '
                                                                                                'in '
                                                                                                'USD '
                                                                                                '(default '
                                                                                                '0 '
                                                                                                '= '
                                                                                                'no '
                                                                                                'floor; '
                                                                                                'stocks '
                                                                                                'with '
                                                                                                'unknown '
                                                                                                'market '
                                                                                                'cap '
                                                                                                'are '
                                                                                                'excluded '
                                                                                                'when '
                                                                                                'set).',
                                                                                 'default': 0.0},
                                                                'minSharePrice': {'location': 'query',
                                                                                  'required': False,
                                                                                  'type': 'number',
                                                                                  'description': 'Minimum '
                                                                                                 'share '
                                                                                                 'price '
                                                                                                 'in '
                                                                                                 'USD '
                                                                                                 '(default '
                                                                                                 '0 '
                                                                                                 '= '
                                                                                                 'no '
                                                                                                 'floor; '
                                                                                                 'unknown '
                                                                                                 'price '
                                                                                                 'excluded '
                                                                                                 'when '
                                                                                                 'set).',
                                                                                  'default': 0.0},
                                                                'minDollarVolume': {'location': 'query',
                                                                                    'required': False,
                                                                                    'type': 'number',
                                                                                    'description': 'Minimum '
                                                                                                   'trailing '
                                                                                                   '3-month '
                                                                                                   'average '
                                                                                                   'daily '
                                                                                                   'dollar '
                                                                                                   'volume '
                                                                                                   'in '
                                                                                                   'USD '
                                                                                                   '(default '
                                                                                                   '0 '
                                                                                                   '= '
                                                                                                   'no '
                                                                                                   'floor; '
                                                                                                   'unknown '
                                                                                                   'volume '
                                                                                                   'excluded '
                                                                                                   'when '
                                                                                                   'set).',
                                                                                    'default': 0.0},
                                                                'limit': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'integer',
                                                                          'description': 'Maximum '
                                                                                         'rows to '
                                                                                         'return '
                                                                                         '(1–500; '
                                                                                         'default '
                                                                                         'varies '
                                                                                         'per '
                                                                                         'endpoint).',
                                                                          'minimum': 1,
                                                                          'maximum': 500},
                                                                'offset': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'integer',
                                                                           'description': 'Rows to '
                                                                                          'skip '
                                                                                          'before '
                                                                                          'the '
                                                                                          'first '
                                                                                          'returned '
                                                                                          'row '
                                                                                          '(default '
                                                                                          '0).'},
                                                                'bottom': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'boolean',
                                                                           'description': 'Walk '
                                                                                          'the '
                                                                                          'ranking '
                                                                                          'from '
                                                                                          'the '
                                                                                          'other '
                                                                                          'end ; '
                                                                                          'heaviest '
                                                                                          'net '
                                                                                          'insider '
                                                                                          'distribution '
                                                                                          '(selling) '
                                                                                          'first. '
                                                                                          'Ranks '
                                                                                          'stay '
                                                                                          'the '
                                                                                          'full-universe '
                                                                                          'positions.',
                                                                           'default': False},
                                                                'ticker': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'string',
                                                                           'description': 'Optional '
                                                                                          'stock '
                                                                                          'ticker '
                                                                                          '(e.g. '
                                                                                          'NVDA): '
                                                                                          'returns '
                                                                                          'that '
                                                                                          'one '
                                                                                          "stock's "
                                                                                          'score '
                                                                                          'and '
                                                                                          'universe '
                                                                                          'rank '
                                                                                          'instead '
                                                                                          'of the '
                                                                                          'leaderboard; '
                                                                                          '404 '
                                                                                          'when '
                                                                                          'the '
                                                                                          'stock '
                                                                                          'is not '
                                                                                          'in the '
                                                                                          'scored '
                                                                                          'universe.'}},
                                                 'live': False},
                    'insider_directory': {'name': 'insider_directory',
                                          'path': '/insiders',
                                          'parameters': {'query': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Search query '
                                                                                  'for insider '
                                                                                  'name '
                                                                                  '(required). '
                                                                                  'Punctuation and '
                                                                                  'word order are '
                                                                                  'ignored. '
                                                                                  'Verified '
                                                                                  'aliases bridge '
                                                                                  'public names to '
                                                                                  'SEC legal '
                                                                                  'names, so '
                                                                                  '"Jensen Huang" '
                                                                                  'resolves "HUANG '
                                                                                  'JEN HSUN" '
                                                                                  'without '
                                                                                  'allowing a '
                                                                                  'short substring '
                                                                                  'such as "ann" '
                                                                                  'to match '
                                                                                  '"JOANNA".'},
                                                         'limit': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Maximum rows to '
                                                                                  'return (1–500; '
                                                                                  'default varies '
                                                                                  'per endpoint).',
                                                                   'minimum': 1,
                                                                   'maximum': 500},
                                                         'offset': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Rows to skip '
                                                                                   'before the '
                                                                                   'first returned '
                                                                                   'row (default '
                                                                                   '0).'}},
                                          'live': False},
                    'investment_adviser_directory': {'name': 'investment_adviser_directory',
                                                     'path': '/investment-advisers',
                                                     'parameters': {'query': {'location': 'query',
                                                                              'required': True,
                                                                              'type': 'string',
                                                                              'description': 'Part '
                                                                                             'of '
                                                                                             'the '
                                                                                             "firm's "
                                                                                             'legal '
                                                                                             'or '
                                                                                             'business '
                                                                                             'name '
                                                                                             '(e.g. '
                                                                                             '"Vanguard", '
                                                                                             '"Renaissance"); '
                                                                                             'required.'},
                                                                    'limit': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'integer',
                                                                              'description': 'Maximum '
                                                                                             'advisers '
                                                                                             'to '
                                                                                             'return '
                                                                                             '(default '
                                                                                             '20, '
                                                                                             'max '
                                                                                             '500; '
                                                                                             'zero '
                                                                                             'or '
                                                                                             'negative '
                                                                                             'values '
                                                                                             'are '
                                                                                             'rejected, '
                                                                                             'values '
                                                                                             'above '
                                                                                             'the '
                                                                                             'maximum '
                                                                                             'are '
                                                                                             'clamped).',
                                                                              'minimum': 1,
                                                                              'maximum': 500}},
                                                     'live': False},
                    'investment_adviser_profile': {'name': 'investment_adviser_profile',
                                                   'path': '/investment-advisers/{crd}',
                                                   'parameters': {'crd': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'integer',
                                                                          'description': 'The '
                                                                                         "adviser's "
                                                                                         'Organization '
                                                                                         'CRD '
                                                                                         'number '
                                                                                         '(e.g. '
                                                                                         '231).'}},
                                                   'live': False},
                    'listings': {'name': 'listings',
                                 'path': '/listings',
                                 'parameters': {'query': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Company name or ticker '
                                                                         'to search for (e.g. '
                                                                         'siemens, ASML or '
                                                                         'XETR:SIE).'},
                                                'isin': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'ISIN to look up (e.g. '
                                                                        'IE00B5BMR087); cannot be '
                                                                        'combined with query.'},
                                                'exchange': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Market identifier '
                                                                            'code to keep (e.g. '
                                                                            'XETR, XAMS, XLIS); '
                                                                            'with neither query '
                                                                            'nor isin it lists '
                                                                            'that exchange. GET '
                                                                            '/v1/markets lists the '
                                                                            'codes.'},
                                                'market': {'location': 'query',
                                                           'required': False,
                                                           'type': 'string',
                                                           'description': 'ISO country code whose '
                                                                          'listings to list (e.g. '
                                                                          'US, DE, PT); cannot be '
                                                                          'combined with query, '
                                                                          'isin or exchange.'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum rows to return '
                                                                         '(1–500; default varies '
                                                                         'per endpoint).',
                                                          'minimum': 1,
                                                          'maximum': 500},
                                                'offset': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Rows to skip before the '
                                                                          'first returned row '
                                                                          '(default 0).'}},
                                 'live': False},
                    'market_calendar': {'name': 'market_calendar',
                                        'path': '/market/calendar',
                                        'parameters': {'year': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Calendar year, '
                                                                               'e.g. 2026 '
                                                                               '(defaults to the '
                                                                               'current year).'}},
                                        'live': False},
                    'market_put_call_ratios': {'name': 'market_put_call_ratios',
                                               'path': '/market/put-call-ratios',
                                               'parameters': {'type': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'Ratio type: '
                                                                                      'Total, '
                                                                                      'Equity, '
                                                                                      'Index, Vix, '
                                                                                      'Etp '
                                                                                      '(default '
                                                                                      'Equity).'},
                                                              'startDate': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'string',
                                                                            'description': 'Start '
                                                                                           'date '
                                                                                           '(yyyy-MM-dd, '
                                                                                           'defaults '
                                                                                           'to 3 '
                                                                                           'months '
                                                                                           'ago).',
                                                                            'format': 'date'},
                                                              'endDate': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': 'End date '
                                                                                         '(yyyy-MM-dd, '
                                                                                         'defaults '
                                                                                         'to '
                                                                                         'today).',
                                                                          'format': 'date'},
                                                              'limit': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': 'Maximum '
                                                                                       'rows to '
                                                                                       'return '
                                                                                       '(1–500; '
                                                                                       'default '
                                                                                       'varies per '
                                                                                       'endpoint).',
                                                                        'minimum': 1,
                                                                        'maximum': 500},
                                                              'offset': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Rows to '
                                                                                        'skip '
                                                                                        'before '
                                                                                        'the first '
                                                                                        'returned '
                                                                                        'row '
                                                                                        '(default '
                                                                                        '0).'}},
                                               'live': False},
                    'market_status': {'name': 'market_status',
                                      'path': '/market/status',
                                      'parameters': {},
                                      'live': False},
                    'market_vix': {'name': 'market_vix',
                                   'path': '/market/vix',
                                   'parameters': {'startDate': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'Start date '
                                                                               '(yyyy-MM-dd, '
                                                                               'defaults to 3 '
                                                                               'months ago).',
                                                                'format': 'date'},
                                                  'endDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'End date '
                                                                             '(yyyy-MM-dd, '
                                                                             'defaults to today).',
                                                              'format': 'date'},
                                                  'limit': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Maximum rows to return '
                                                                           '(1–500; default varies '
                                                                           'per endpoint).',
                                                            'minimum': 1,
                                                            'maximum': 500},
                                                  'offset': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Rows to skip before '
                                                                            'the first returned '
                                                                            'row (default 0).'}},
                                   'live': False},
                    'markets': {'name': 'markets',
                                'path': '/markets',
                                'parameters': {},
                                'live': False},
                    'prices_latest': {'name': 'prices_latest',
                                      'path': '/prices/latest',
                                      'parameters': {'tickers': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Comma-separated '
                                                                                'exact listed '
                                                                                'tickers (e.g. '
                                                                                'GOOG,GOOGL,BRK-A,BRK-B), '
                                                                                'or MIC:TICKER for '
                                                                                'a listing on '
                                                                                'another exchange '
                                                                                '(e.g. '
                                                                                'AAPL,XETR:SIE,XAMS:ASML), '
                                                                                'max 25. A missing '
                                                                                'listing is never '
                                                                                'replaced by its '
                                                                                'sibling; dot '
                                                                                'class-share '
                                                                                'spelling such as '
                                                                                'BRK.B is accepted '
                                                                                'as BRK-B.'}},
                                      'live': False},
                    'quotes': {'name': 'quotes',
                               'path': '/quotes',
                               'parameters': {'tickers': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Comma-separated exact '
                                                                         'listed tickers (e.g. '
                                                                         'GOOG,GOOGL,BRK-A,BRK-B) '
                                                                         'or Canadian, Euronext '
                                                                         'and NSE MIC:TICKER '
                                                                         'symbols (e.g. XTSE:RY, '
                                                                         'XPAR:AIR, '
                                                                         'XNSE:RELIANCE), max '
                                                                         '25.'}},
                               'live': False},
                    'screener_stocks': {'name': 'screener_stocks',
                                        'path': '/screener/stocks',
                                        'parameters': {'minMarketCap': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'number',
                                                                        'description': 'Minimum '
                                                                                       'market '
                                                                                       'capitalization '
                                                                                       'in USD.'},
                                                       'maxMarketCap': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'number',
                                                                        'description': 'Maximum '
                                                                                       'market '
                                                                                       'capitalization '
                                                                                       'in USD.'},
                                                       'minPrice': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'number',
                                                                    'description': 'Minimum share '
                                                                                   'price in USD.'},
                                                       'maxPrice': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'number',
                                                                    'description': 'Maximum share '
                                                                                   'price in USD.'},
                                                       'minFilerCount': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Minimum '
                                                                                        'number of '
                                                                                        '13F '
                                                                                        'institutional '
                                                                                        'filers.'},
                                                       'maxFilerCount': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Maximum '
                                                                                        'number of '
                                                                                        '13F '
                                                                                        'institutional '
                                                                                        'filers.'},
                                                       'minFilerDelta': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Minimum '
                                                                                        'quarter-over-quarter '
                                                                                        'change in '
                                                                                        'filer '
                                                                                        'count.'},
                                                       'maxFilerDelta': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Maximum '
                                                                                        'quarter-over-quarter '
                                                                                        'change in '
                                                                                        'filer '
                                                                                        'count.'},
                                                       'minShortInterestPercent': {'location': 'query',
                                                                                   'required': False,
                                                                                   'type': 'number',
                                                                                   'description': 'Minimum '
                                                                                                  'short '
                                                                                                  'interest '
                                                                                                  'as '
                                                                                                  'a '
                                                                                                  'percent '
                                                                                                  'of '
                                                                                                  'shares '
                                                                                                  'outstanding '
                                                                                                  '(0-100).',
                                                                                   'minimum': 0,
                                                                                   'maximum': 100},
                                                       'maxShortInterestPercent': {'location': 'query',
                                                                                   'required': False,
                                                                                   'type': 'number',
                                                                                   'description': 'Maximum '
                                                                                                  'short '
                                                                                                  'interest '
                                                                                                  'as '
                                                                                                  'a '
                                                                                                  'percent '
                                                                                                  'of '
                                                                                                  'shares '
                                                                                                  'outstanding '
                                                                                                  '(0-100).',
                                                                                   'minimum': 0,
                                                                                   'maximum': 100},
                                                       'minDaysToCover': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'number',
                                                                          'description': 'Minimum '
                                                                                         'days to '
                                                                                         'cover.'},
                                                       'maxDaysToCover': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'number',
                                                                          'description': 'Maximum '
                                                                                         'days to '
                                                                                         'cover.'},
                                                       'minSqueezeScore': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'number',
                                                                           'description': 'Minimum '
                                                                                          'composite '
                                                                                          'short-squeeze '
                                                                                          'score '
                                                                                          '(0-100).',
                                                                           'minimum': 0,
                                                                           'maximum': 100},
                                                       'maxSqueezeScore': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'number',
                                                                           'description': 'Maximum '
                                                                                          'composite '
                                                                                          'short-squeeze '
                                                                                          'score '
                                                                                          '(0-100).',
                                                                           'minimum': 0,
                                                                           'maximum': 100},
                                                       'minInsiderSentiment': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'number',
                                                                               'description': 'Minimum '
                                                                                              'composite '
                                                                                              'insider-sentiment '
                                                                                              'score '
                                                                                              '(0-100).',
                                                                               'minimum': 0,
                                                                               'maximum': 100},
                                                       'maxInsiderSentiment': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'number',
                                                                               'description': 'Maximum '
                                                                                              'composite '
                                                                                              'insider-sentiment '
                                                                                              'score '
                                                                                              '(0-100).',
                                                                               'minimum': 0,
                                                                               'maximum': 100},
                                                       'minNetInsiderBuy': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'number',
                                                                            'description': 'Minimum '
                                                                                           'net '
                                                                                           'open-market '
                                                                                           'insider '
                                                                                           'buying '
                                                                                           'by '
                                                                                           'officers '
                                                                                           'and '
                                                                                           'directors '
                                                                                           'in USD '
                                                                                           'over '
                                                                                           'the '
                                                                                           'trailing '
                                                                                           '90 '
                                                                                           'days.'},
                                                       'maxNetInsiderBuy': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'number',
                                                                            'description': 'Maximum '
                                                                                           'net '
                                                                                           'open-market '
                                                                                           'insider '
                                                                                           'buying '
                                                                                           'by '
                                                                                           'officers '
                                                                                           'and '
                                                                                           'directors '
                                                                                           'in USD '
                                                                                           'over '
                                                                                           'the '
                                                                                           'trailing '
                                                                                           '90 '
                                                                                           'days.'},
                                                       'hasGoingConcernDoubt': {'location': 'query',
                                                                                'required': False,
                                                                                'type': 'boolean',
                                                                                'description': 'True '
                                                                                               'keeps '
                                                                                               'only '
                                                                                               'companies '
                                                                                               'with '
                                                                                               'unalleviated '
                                                                                               'going-concern '
                                                                                               'doubt; '
                                                                                               'false '
                                                                                               'keeps '
                                                                                               'only '
                                                                                               'companies '
                                                                                               'without '
                                                                                               'it.'},
                                                       'sector': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Exact sector '
                                                                                 'name (e.g. '
                                                                                 'Technology, '
                                                                                 'Healthcare). An '
                                                                                 'unknown name is '
                                                                                 'a 400 listing '
                                                                                 'the accepted '
                                                                                 'sectors.'},
                                                       'industry': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'Exact industry '
                                                                                   'name (e.g. '
                                                                                   'Semiconductors). '
                                                                                   'Prefer sector '
                                                                                   'for broad '
                                                                                   'groups; an '
                                                                                   'unknown name '
                                                                                   'is a 400.'},
                                                       'index': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Restrict to '
                                                                                'members of a '
                                                                                'covered index, by '
                                                                                'slug or name '
                                                                                '(e.g. sp-500, '
                                                                                '"S&P 500", SPX). '
                                                                                'A name matching '
                                                                                'no covered index '
                                                                                'is a 400 listing '
                                                                                'the covered '
                                                                                'ones.'},
                                                       'market': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Listing markets '
                                                                                 'to screen, as '
                                                                                 'comma-separated '
                                                                                 'ISO country '
                                                                                 'codes (for '
                                                                                 'example '
                                                                                 '`GB,FR`), or '
                                                                                 '`all` for every '
                                                                                 'market. Omitted '
                                                                                 'means `US`. A '
                                                                                 "non-US row's "
                                                                                 'ticker is the '
                                                                                 'qualified '
                                                                                 '`MIC:TICKER` '
                                                                                 'symbol (for '
                                                                                 'example '
                                                                                 '`XPAR:AIR`) and '
                                                                                 'its price and '
                                                                                 'market cap are '
                                                                                 'converted to USD '
                                                                                 'at the official '
                                                                                 'rate; '
                                                                                 '`localPrice` and '
                                                                                 '`currency` carry '
                                                                                 'the traded '
                                                                                 'close. An '
                                                                                 'unknown code is '
                                                                                 'a 400 listing '
                                                                                 'the covered '
                                                                                 'markets.'},
                                                       'minPe': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'number',
                                                                 'description': 'Minimum '
                                                                                'trailing-twelve-month '
                                                                                'price-to-earnings '
                                                                                'ratio.'},
                                                       'maxPe': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'number',
                                                                 'description': 'Maximum '
                                                                                'trailing-twelve-month '
                                                                                'price-to-earnings '
                                                                                'ratio (e.g. 15 '
                                                                                'for value '
                                                                                'screens).'},
                                                       'minDividendYield': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'number',
                                                                            'description': 'Minimum '
                                                                                           'trailing '
                                                                                           'dividend '
                                                                                           'yield '
                                                                                           'in '
                                                                                           'percent '
                                                                                           '(e.g. '
                                                                                           '3 = '
                                                                                           '3%).'},
                                                       'maxDividendYield': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'number',
                                                                            'description': 'Maximum '
                                                                                           'trailing '
                                                                                           'dividend '
                                                                                           'yield '
                                                                                           'in '
                                                                                           'percent.'},
                                                       'minRevenueGrowth': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'number',
                                                                            'description': 'Minimum '
                                                                                           'revenue '
                                                                                           'growth '
                                                                                           'in '
                                                                                           'percent, '
                                                                                           'latest '
                                                                                           'quarter '
                                                                                           'vs the '
                                                                                           'same '
                                                                                           'quarter '
                                                                                           'a year '
                                                                                           'earlier.'},
                                                       'maxRevenueGrowth': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'number',
                                                                            'description': 'Maximum '
                                                                                           'revenue '
                                                                                           'growth '
                                                                                           'in '
                                                                                           'percent, '
                                                                                           'latest '
                                                                                           'quarter '
                                                                                           'vs the '
                                                                                           'same '
                                                                                           'quarter '
                                                                                           'a year '
                                                                                           'earlier.'},
                                                       'minGrossMargin': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'number',
                                                                          'description': 'Minimum '
                                                                                         'gross '
                                                                                         'margin '
                                                                                         'in '
                                                                                         'percent '
                                                                                         '(0-100).',
                                                                          'minimum': 0,
                                                                          'maximum': 100},
                                                       'maxGrossMargin': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'number',
                                                                          'description': 'Maximum '
                                                                                         'gross '
                                                                                         'margin '
                                                                                         'in '
                                                                                         'percent '
                                                                                         '(0-100).',
                                                                          'minimum': 0,
                                                                          'maximum': 100},
                                                       'minDollarVolume': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'number',
                                                                           'description': 'Minimum '
                                                                                          'trailing-3-month '
                                                                                          'average '
                                                                                          'daily '
                                                                                          'dollar '
                                                                                          'volume '
                                                                                          'in USD '
                                                                                          '(e.g. '
                                                                                          '5000000 '
                                                                                          '= '
                                                                                          '$5M/day).'},
                                                       'maxDollarVolume': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'number',
                                                                           'description': 'Maximum '
                                                                                          'trailing-3-month '
                                                                                          'average '
                                                                                          'daily '
                                                                                          'dollar '
                                                                                          'volume '
                                                                                          'in '
                                                                                          'USD.'},
                                                       'minNetIncome': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'number',
                                                                        'description': 'Minimum '
                                                                                       'trailing-twelve-month '
                                                                                       'net income '
                                                                                       'in USD (0 '
                                                                                       'keeps '
                                                                                       'profitable '
                                                                                       'companies '
                                                                                       'only).'},
                                                       'maxNetIncome': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'number',
                                                                        'description': 'Maximum '
                                                                                       'trailing-twelve-month '
                                                                                       'net income '
                                                                                       'in USD.'},
                                                       'minInstitutionalOwnership': {'location': 'query',
                                                                                     'required': False,
                                                                                     'type': 'number',
                                                                                     'description': 'Minimum '
                                                                                                    'institutional '
                                                                                                    'ownership: '
                                                                                                    '13F '
                                                                                                    'shares '
                                                                                                    'over '
                                                                                                    'shares '
                                                                                                    'outstanding, '
                                                                                                    'in '
                                                                                                    'percent.'},
                                                       'maxInstitutionalOwnership': {'location': 'query',
                                                                                     'required': False,
                                                                                     'type': 'number',
                                                                                     'description': 'Maximum '
                                                                                                    'institutional '
                                                                                                    'ownership '
                                                                                                    'in '
                                                                                                    'percent.'},
                                                       'minConvictionShare': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'number',
                                                                              'description': 'Minimum '
                                                                                             'percent '
                                                                                             'of '
                                                                                             'the '
                                                                                             "stock's "
                                                                                             '13F '
                                                                                             'filers '
                                                                                             'holding '
                                                                                             'it '
                                                                                             'among '
                                                                                             'their '
                                                                                             'ten '
                                                                                             'largest '
                                                                                             'positions.'},
                                                       'maxConvictionShare': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'number',
                                                                              'description': 'Maximum '
                                                                                             'conviction '
                                                                                             'share '
                                                                                             'in '
                                                                                             'percent.'},
                                                       'minCrowding': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'number',
                                                                       'description': 'Minimum '
                                                                                      'crowding: '
                                                                                      'shares held '
                                                                                      'by '
                                                                                      'high-turnover '
                                                                                      '13F filers '
                                                                                      'and '
                                                                                      'private-fund '
                                                                                      'advisers, '
                                                                                      'in percent '
                                                                                      'of shares '
                                                                                      'outstanding.'},
                                                       'maxCrowding': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'number',
                                                                       'description': 'Maximum '
                                                                                      'crowding in '
                                                                                      'percent of '
                                                                                      'shares '
                                                                                      'outstanding.'},
                                                       'minPrivateFundOwnership': {'location': 'query',
                                                                                   'required': False,
                                                                                   'type': 'number',
                                                                                   'description': 'Minimum '
                                                                                                  'ownership '
                                                                                                  'by '
                                                                                                  '13F '
                                                                                                  'filers '
                                                                                                  'that '
                                                                                                  'advise '
                                                                                                  'private '
                                                                                                  'funds '
                                                                                                  '(Form '
                                                                                                  'ADV), '
                                                                                                  'in '
                                                                                                  'percent '
                                                                                                  'of '
                                                                                                  'shares '
                                                                                                  'outstanding.'},
                                                       'maxPrivateFundOwnership': {'location': 'query',
                                                                                   'required': False,
                                                                                   'type': 'number',
                                                                                   'description': 'Maximum '
                                                                                                  'private-fund '
                                                                                                  'adviser '
                                                                                                  'ownership '
                                                                                                  'in '
                                                                                                  'percent '
                                                                                                  'of '
                                                                                                  'shares '
                                                                                                  'outstanding.'},
                                                       'minActiveHolderChange': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'number',
                                                                                 'description': 'Minimum '
                                                                                                'like-for-like '
                                                                                                'share '
                                                                                                'change '
                                                                                                'of '
                                                                                                'actively '
                                                                                                'managed '
                                                                                                '13F '
                                                                                                'holders '
                                                                                                'over '
                                                                                                'the '
                                                                                                'quarter, '
                                                                                                'in '
                                                                                                'percent.'},
                                                       'maxActiveHolderChange': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'number',
                                                                                 'description': 'Maximum '
                                                                                                'like-for-like '
                                                                                                'share '
                                                                                                'change '
                                                                                                'of '
                                                                                                'actively '
                                                                                                'managed '
                                                                                                '13F '
                                                                                                'holders, '
                                                                                                'in '
                                                                                                'percent.'},
                                                       'minHolderTenure': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'number',
                                                                           'description': 'Minimum '
                                                                                          'value-weighted '
                                                                                          'holder '
                                                                                          'tenure '
                                                                                          'in '
                                                                                          'quarters.'},
                                                       'maxHolderTenure': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'number',
                                                                           'description': 'Maximum '
                                                                                          'value-weighted '
                                                                                          'holder '
                                                                                          'tenure '
                                                                                          'in '
                                                                                          'quarters.'},
                                                       'minEstimatedCostGap': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'number',
                                                                               'description': 'Minimum '
                                                                                              'quarter-end '
                                                                                              'price '
                                                                                              'versus '
                                                                                              'the '
                                                                                              "holders' "
                                                                                              'estimated '
                                                                                              'average '
                                                                                              'cost, '
                                                                                              'in '
                                                                                              'percent '
                                                                                              '(negative '
                                                                                              'means '
                                                                                              'an '
                                                                                              'estimated '
                                                                                              'loss).'},
                                                       'maxEstimatedCostGap': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'number',
                                                                               'description': 'Maximum '
                                                                                              'quarter-end '
                                                                                              'price '
                                                                                              'versus '
                                                                                              'the '
                                                                                              "holders' "
                                                                                              'estimated '
                                                                                              'average '
                                                                                              'cost, '
                                                                                              'in '
                                                                                              'percent.'},
                                                       'sortBy': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Sort key: '
                                                                                 'marketcap, '
                                                                                 'ticker, name, '
                                                                                 'price, filers, '
                                                                                 'filerdelta, '
                                                                                 'sipct, dtc, '
                                                                                 'squeeze, '
                                                                                 'sentiment, '
                                                                                 'insiderbuy, pe, '
                                                                                 'divyield, '
                                                                                 'revgrowth, '
                                                                                 'grossmargin, '
                                                                                 'dollarvol, '
                                                                                 'netincome, '
                                                                                 'instown, conv, '
                                                                                 'crowd, pfown, '
                                                                                 'actlfl, tenure, '
                                                                                 'or costgap '
                                                                                 '(default '
                                                                                 'marketcap). An '
                                                                                 'unknown key is a '
                                                                                 '400, never '
                                                                                 'silently '
                                                                                 'ignored.',
                                                                  'default': 'marketcap'},
                                                       'sortAscending': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'boolean',
                                                                         'description': 'Sort '
                                                                                        'ascending '
                                                                                        'instead '
                                                                                        'of '
                                                                                        'descending.',
                                                                         'default': False},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum rows to '
                                                                                'return (default '
                                                                                '50, max 200; zero '
                                                                                'or negative '
                                                                                'values are '
                                                                                'rejected, values '
                                                                                'above the maximum '
                                                                                'are clamped).',
                                                                 'minimum': 1,
                                                                 'maximum': 200},
                                                       'page': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Result page, '
                                                                               '1-based (default '
                                                                               '1) ; combine with '
                                                                               'limit to walk past '
                                                                               'the first page. A '
                                                                               'page past the end '
                                                                               'returns the last '
                                                                               'real page (see the '
                                                                               "response's page "
                                                                               'field).'},
                                                       'tickers': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Comma-separated '
                                                                                  'list of up to '
                                                                                  '200 tickers to '
                                                                                  'restrict the '
                                                                                  'screen to, so a '
                                                                                  'caller can '
                                                                                  'score stocks '
                                                                                  'they already '
                                                                                  'hold instead of '
                                                                                  'searching the '
                                                                                  'market. Every '
                                                                                  'other bound '
                                                                                  'still applies. '
                                                                                  'Class-share '
                                                                                  'dots (BRK.B) '
                                                                                  'resolve to the '
                                                                                  'listed form and '
                                                                                  'a secondary '
                                                                                  'listing '
                                                                                  'resolves to its '
                                                                                  'issuer and is '
                                                                                  'named in '
                                                                                  'answeredAs; '
                                                                                  'symbols outside '
                                                                                  'the universe '
                                                                                  'come back in '
                                                                                  "the response's "
                                                                                  'notFound array, '
                                                                                  'and covered '
                                                                                  'symbols the '
                                                                                  'market or a '
                                                                                  'bound left out '
                                                                                  'in leftOut, '
                                                                                  'each with its '
                                                                                  'reason. A '
                                                                                  'listing outside '
                                                                                  'the US is its '
                                                                                  'MIC:TICKER '
                                                                                  'symbol '
                                                                                  '(XTSE:SHOP, '
                                                                                  'XPAR:AIR) or '
                                                                                  'its '
                                                                                  'exchange-suffixed '
                                                                                  'symbol '
                                                                                  '(0700.HK, '
                                                                                  'SAP.DE), never '
                                                                                  'the bare '
                                                                                  'ticker; naming '
                                                                                  'one screens '
                                                                                  'every market '
                                                                                  'unless market '
                                                                                  'is set.'},
                                                       'format': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Response format: '
                                                                                 'omit or `json` '
                                                                                 'for the JSON '
                                                                                 'envelope, `csv` '
                                                                                 'for a flat CSV '
                                                                                 'file. CSV '
                                                                                 'headers are the '
                                                                                 'stable cols keys '
                                                                                 'rather than '
                                                                                 'display labels, '
                                                                                 'and the '
                                                                                 "envelope's "
                                                                                 'paging metadata '
                                                                                 'rides on the '
                                                                                 'X-Screener-Total-Count, '
                                                                                 'X-Screener-Page, '
                                                                                 'X-Screener-Total-Pages, '
                                                                                 'X-Screener-Not-Found '
                                                                                 'and '
                                                                                 'X-Screener-Not-Found-Count '
                                                                                 'response '
                                                                                 'headers. Any '
                                                                                 'other value is a '
                                                                                 '400.'},
                                                       'cols': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'Comma-separated '
                                                                               'CSV column keys '
                                                                               '(for example '
                                                                               '`pe,de,roic,volatility`), '
                                                                               'applying only with '
                                                                               '`format=csv`; '
                                                                               'passing it without '
                                                                               'CSV is a 400 '
                                                                               'rather than a '
                                                                               'silently ignored '
                                                                               'parameter. An '
                                                                               'unknown or empty '
                                                                               'key list is a 400. '
                                                                               'Omitted means the '
                                                                               'default column '
                                                                               'set, and `none` '
                                                                               'means the pinned '
                                                                               'columns only. '
                                                                               'Every file starts '
                                                                               'with four pinned '
                                                                               'fields, `ticker`, '
                                                                               '`name`, `price` '
                                                                               'and `marketcap`, '
                                                                               'then one column '
                                                                               'per key passed; '
                                                                               'there is no '
                                                                               '`ticker` key of '
                                                                               'its own because '
                                                                               'the pinned '
                                                                               '`company` column '
                                                                               'emits ticker and '
                                                                               'name together.'}},
                                        'live': False,
                                        'json_only': True}},
 'filings': {'filings': {'name': 'filings',
                         'path': '/filings',
                         'parameters': {'ticker': {'location': 'query',
                                                   'required': False,
                                                   'type': 'string',
                                                   'description': 'Optional stock ticker symbol '
                                                                  '(e.g. AAPL), or MIC:TICKER for '
                                                                  'a listing outside the US (e.g. '
                                                                  'XPAR:AIR); omit for a '
                                                                  'market-wide feed.'},
                                        'documentType': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'Document type filter, by '
                                                                        'value (e.g. TenK) or form '
                                                                        'label (e.g. 10-K). Also '
                                                                        'accepts '
                                                                        'EarningsCallTranscript '
                                                                        'for call transcripts, '
                                                                        'IrNews for '
                                                                        'investor-relations news '
                                                                        'and EsefAnnualReport for '
                                                                        'a European annual report '
                                                                        'and EsefReport for '
                                                                        'another European ESEF '
                                                                        'report; an unknown value '
                                                                        'returns a 400 listing '
                                                                        'every valid value.'},
                                        'startDate': {'location': 'query',
                                                      'required': False,
                                                      'type': 'string',
                                                      'description': 'Earliest filing date '
                                                                     '(yyyy-MM-dd).',
                                                      'format': 'date'},
                                        'endDate': {'location': 'query',
                                                    'required': False,
                                                    'type': 'string',
                                                    'description': 'Latest filing date '
                                                                   '(yyyy-MM-dd).',
                                                    'format': 'date'},
                                        'itemNumber': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Exact SEC current-report '
                                                                      'item number (e.g. 2.02 or '
                                                                      '5.02).'},
                                        'limit': {'location': 'query',
                                                  'required': False,
                                                  'type': 'integer',
                                                  'description': 'Maximum rows to return (1–500; '
                                                                 'default varies per endpoint).',
                                                  'minimum': 1,
                                                  'maximum': 500},
                                        'offset': {'location': 'query',
                                                   'required': False,
                                                   'type': 'integer',
                                                   'description': 'Rows to skip before the first '
                                                                  'returned row (default 0).'}},
                         'live': False},
             'filing_search': {'name': 'filing_search',
                               'path': '/filings/search',
                               'parameters': {'query': {'location': 'query',
                                                        'required': True,
                                                        'type': 'string',
                                                        'description': 'Search query ; plain '
                                                                       'keywords or a short '
                                                                       'natural-language phrase '
                                                                       '(required). Concise, '
                                                                       'filing-phrased terms (e.g. '
                                                                       "'Data Center revenue') "
                                                                       'still rank best.'},
                                              'documentType': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Document type '
                                                                              'filter ; one value '
                                                                              'or a '
                                                                              'comma-separated '
                                                                              'list (e.g. '
                                                                              'TenK,TenQ), by '
                                                                              'value or form label '
                                                                              '(e.g. 10-K).'},
                                              'startDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Earliest filing date '
                                                                           '(yyyy-MM-dd).',
                                                            'format': 'date'},
                                              'endDate': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Latest filing date '
                                                                         '(yyyy-MM-dd).',
                                                          'format': 'date'},
                                              'limit': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Maximum excerpts to return '
                                                                       '(default 5, max 500).',
                                                        'minimum': 1,
                                                        'maximum': 500},
                                              'excludeTickers': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Tickers whose '
                                                                                'filings are '
                                                                                'excluded from the '
                                                                                'results ; one '
                                                                                'value or a '
                                                                                'comma-separated '
                                                                                'list (e.g. '
                                                                                'AAPL,MSFT). Use '
                                                                                "when a company's "
                                                                                'own filings would '
                                                                                'dominate the '
                                                                                'results for a '
                                                                                'query about its '
                                                                                'market.'},
                                              'maxResultsPerCompany': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': 'Maximum '
                                                                                      'excerpts '
                                                                                      'from any '
                                                                                      'single '
                                                                                      'company '
                                                                                      '(default 0 '
                                                                                      '= '
                                                                                      'unlimited). '
                                                                                      'Set a small '
                                                                                      'value to '
                                                                                      'spread '
                                                                                      'results '
                                                                                      'across more '
                                                                                      'companies '
                                                                                      'for '
                                                                                      'discovery-style '
                                                                                      'queries.',
                                                                       'default': 0},
                                              'match': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'How the query matches: '
                                                                       'ranked (default) for '
                                                                       'relevance-ranked retrieval '
                                                                       'that broadens to any of '
                                                                       'the words when results are '
                                                                       'sparse, or phrase for only '
                                                                       'the excerpts containing '
                                                                       "the query's words "
                                                                       'consecutively and in order '
                                                                       '(case and punctuation '
                                                                       'ignored).'}},
                               'live': False},
             'filing_keyword_search': {'name': 'filing_keyword_search',
                                       'path': '/filings/{documentId}/keyword-search',
                                       'parameters': {'documentId': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'string',
                                                                     'description': 'Document id '
                                                                                    'from the '
                                                                                    'filings list.',
                                                                     'format': 'uuid'},
                                                      'keyword': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Keyword or '
                                                                                 'phrase to search '
                                                                                 'for (required).'},
                                                      'limit': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Maximum matches to '
                                                                               'return (default '
                                                                               '20, max 500).',
                                                                'minimum': 1,
                                                                'maximum': 500}},
                                       'live': False},
             'filing_lines': {'name': 'filing_lines',
                              'path': '/filings/{documentId}/lines',
                              'parameters': {'documentId': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Document id from the '
                                                                           'filings list.',
                                                            'format': 'uuid'},
                                             'startLine': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'First line to read '
                                                                          '(1-based, inclusive; '
                                                                          'required).'},
                                             'endLine': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Last line to read '
                                                                        '(1-based, inclusive; '
                                                                        'required, capped at the '
                                                                        "document's last line; a "
                                                                        'window wider than 500 '
                                                                        'lines returns its first '
                                                                        '500 with hasMore).'}},
                              'live': False},
             'filing_search_document': {'name': 'filing_search_document',
                                        'path': '/filings/{documentId}/search',
                                        'parameters': {'documentId': {'location': 'path',
                                                                      'required': True,
                                                                      'type': 'string',
                                                                      'description': 'Document id '
                                                                                     'from the '
                                                                                     'filings list '
                                                                                     'or a search '
                                                                                     'result.',
                                                                      'format': 'uuid'},
                                                       'query': {'location': 'query',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'Search query ; '
                                                                                'plain keywords or '
                                                                                'a short '
                                                                                'natural-language '
                                                                                'phrase '
                                                                                '(required).'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum excerpts '
                                                                                'to return '
                                                                                '(default 5, max '
                                                                                '500).',
                                                                 'minimum': 1,
                                                                 'maximum': 500}},
                                        'live': False},
             'company_filings': {'name': 'company_filings',
                                 'path': '/stocks/{ticker}/filings',
                                 'parameters': {'ticker': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': 'Stock ticker symbol '
                                                                          '(e.g. AAPL), or '
                                                                          'MIC:TICKER for a '
                                                                          'listing outside the US '
                                                                          '(e.g. XPAR:AIR).'},
                                                'documentType': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Document type '
                                                                                'filter, by value '
                                                                                '(e.g. TenK) or '
                                                                                'form label (e.g. '
                                                                                '10-K). Also '
                                                                                'accepts '
                                                                                'EarningsCallTranscript '
                                                                                'for call '
                                                                                'transcripts, '
                                                                                'IrNews for '
                                                                                'investor-relations '
                                                                                'news and '
                                                                                'EsefAnnualReport '
                                                                                'for a European '
                                                                                'annual report and '
                                                                                'EsefReport for '
                                                                                'another European '
                                                                                'ESEF report; an '
                                                                                'unknown value '
                                                                                'returns a 400 '
                                                                                'listing every '
                                                                                'valid value.'},
                                                'startDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Earliest filing date '
                                                                             '(yyyy-MM-dd).',
                                                              'format': 'date'},
                                                'endDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Latest filing date '
                                                                           '(yyyy-MM-dd).',
                                                            'format': 'date'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum rows to return '
                                                                         '(1–500; default varies '
                                                                         'per endpoint).',
                                                          'minimum': 1,
                                                          'maximum': 500},
                                                'offset': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Rows to skip before the '
                                                                          'first returned row '
                                                                          '(default 0).'},
                                                'itemNumber': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Exact SEC '
                                                                              'current-report item '
                                                                              'number (e.g. 2.02 '
                                                                              'or 5.02).'}},
                                 'live': False},
             'company_filing_search': {'name': 'company_filing_search',
                                       'path': '/stocks/{ticker}/filings/search',
                                       'parameters': {'ticker': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'Company ticker '
                                                                                'symbol (e.g. '
                                                                                'AAPL).'},
                                                      'query': {'location': 'query',
                                                                'required': True,
                                                                'type': 'string',
                                                                'description': 'Search query ; '
                                                                               'plain keywords or '
                                                                               'a short '
                                                                               'natural-language '
                                                                               'phrase (required). '
                                                                               'Concise, '
                                                                               'filing-phrased '
                                                                               "terms (e.g. 'Data "
                                                                               "Center revenue') "
                                                                               'still rank best.'},
                                                      'documentType': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'Document '
                                                                                      'type filter '
                                                                                      '; one value '
                                                                                      'or a '
                                                                                      'comma-separated '
                                                                                      'list (e.g. '
                                                                                      'TenK,TenQ), '
                                                                                      'by value or '
                                                                                      'form label '
                                                                                      '(e.g. '
                                                                                      '10-K).'},
                                                      'startDate': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'Earliest '
                                                                                   'filing date '
                                                                                   '(yyyy-MM-dd).',
                                                                    'format': 'date'},
                                                      'endDate': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Latest filing '
                                                                                 'date '
                                                                                 '(yyyy-MM-dd).',
                                                                  'format': 'date'},
                                                      'limit': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Maximum excerpts '
                                                                               'to return (default '
                                                                               '5, max 500).',
                                                                'minimum': 1,
                                                                'maximum': 500},
                                                      'match': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'How the query '
                                                                               'matches: ranked '
                                                                               '(default) for '
                                                                               'relevance-ranked '
                                                                               'retrieval that '
                                                                               'broadens to any of '
                                                                               'the words when '
                                                                               'results are '
                                                                               'sparse, or phrase '
                                                                               'for only the '
                                                                               'excerpts '
                                                                               'containing the '
                                                                               "query's words "
                                                                               'consecutively and '
                                                                               'in order (case and '
                                                                               'punctuation '
                                                                               'ignored).'}},
                                       'live': False}},
 'investor_events': {'investor_events_recent': {'name': 'investor_events_recent',
                                                'path': '/investor-events/recent',
                                                'parameters': {'since': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'string',
                                                                         'description': 'First '
                                                                                        'call date '
                                                                                        'to '
                                                                                        'include, '
                                                                                        'yyyy-MM-dd '
                                                                                        '(default '
                                                                                        '7 days '
                                                                                        'before '
                                                                                        'until).',
                                                                         'format': 'date'},
                                                               'until': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'string',
                                                                         'description': 'Day after '
                                                                                        'the last '
                                                                                        'call date '
                                                                                        'to '
                                                                                        'include, '
                                                                                        'yyyy-MM-dd '
                                                                                        '(default '
                                                                                        'tomorrow, '
                                                                                        'so '
                                                                                        "today's "
                                                                                        'calls '
                                                                                        'count). '
                                                                                        'The '
                                                                                        'window '
                                                                                        'may span '
                                                                                        'at most '
                                                                                        '31 days.',
                                                                         'format': 'date'},
                                                               'eventType': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'string',
                                                                             'description': 'Optional '
                                                                                            'event '
                                                                                            'type: '
                                                                                            'EarningsCall, '
                                                                                            'CapitalMarketsDay, '
                                                                                            'InvestorUpdate, '
                                                                                            'AGM, '
                                                                                            'Conference, '
                                                                                            'FiresideChat, '
                                                                                            'or '
                                                                                            'MAndA.'},
                                                               'market': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': 'Listing '
                                                                                         'markets '
                                                                                         'as '
                                                                                         'comma-separated '
                                                                                         'ISO '
                                                                                         'country '
                                                                                         'codes '
                                                                                         '(for '
                                                                                         'example '
                                                                                         'GB,FR), '
                                                                                         'or all '
                                                                                         'for '
                                                                                         'every '
                                                                                         'market. '
                                                                                         'Omitted '
                                                                                         'means '
                                                                                         'US.'},
                                                               'minMarketCap': {'location': 'query',
                                                                                'required': False,
                                                                                'type': 'number',
                                                                                'description': 'Minimum '
                                                                                               'market '
                                                                                               'capitalization '
                                                                                               'in '
                                                                                               'US '
                                                                                               'dollars. '
                                                                                               'Accepted '
                                                                                               'only '
                                                                                               'with '
                                                                                               'the '
                                                                                               'US '
                                                                                               'market, '
                                                                                               'because '
                                                                                               'other '
                                                                                               'markets '
                                                                                               'carry '
                                                                                               'local-currency '
                                                                                               'figures.'},
                                                               'tickers': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'string',
                                                                           'description': 'Comma-separated '
                                                                                          'tickers '
                                                                                          '(max '
                                                                                          '25) to '
                                                                                          'follow '
                                                                                          'instead '
                                                                                          'of a '
                                                                                          'market: '
                                                                                          'a US '
                                                                                          'ticker, '
                                                                                          'or '
                                                                                          'MIC:TICKER '
                                                                                          'for a '
                                                                                          'listing '
                                                                                          'outside '
                                                                                          'the US '
                                                                                          '(for '
                                                                                          'example '
                                                                                          'XLON:VOD). '
                                                                                          'Only '
                                                                                          'these '
                                                                                          "companies' "
                                                                                          'events '
                                                                                          'are '
                                                                                          'returned, '
                                                                                          'whatever '
                                                                                          'their '
                                                                                          'market. '
                                                                                          'Cannot '
                                                                                          'be '
                                                                                          'combined '
                                                                                          'with '
                                                                                          'market '
                                                                                          'or '
                                                                                          'minMarketCap; '
                                                                                          'an '
                                                                                          'unknown '
                                                                                          'ticker '
                                                                                          'returns '
                                                                                          '404.'},
                                                               'limit': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Maximum '
                                                                                        'rows to '
                                                                                        'return '
                                                                                        '(1–500; '
                                                                                        'default '
                                                                                        'varies '
                                                                                        'per '
                                                                                        'endpoint).',
                                                                         'minimum': 1,
                                                                         'maximum': 500},
                                                               'offset': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'integer',
                                                                          'description': 'Rows to '
                                                                                         'skip '
                                                                                         'before '
                                                                                         'the '
                                                                                         'first '
                                                                                         'returned '
                                                                                         'row '
                                                                                         '(default '
                                                                                         '0).'}},
                                                'live': False},
                     'event_live_transcript': {'name': 'event_live_transcript',
                                               'path': '/investor-events/{eventId}/live-transcript',
                                               'parameters': {'eventId': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'string',
                                                                          'description': 'Investor '
                                                                                         'event id '
                                                                                         'from the '
                                                                                         'investor-events '
                                                                                         'list.',
                                                                          'format': 'uuid'},
                                                              'after': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': 'The '
                                                                                       'highest '
                                                                                       'line seq '
                                                                                       'already '
                                                                                       'received '
                                                                                       '(default '
                                                                                       '-1, the '
                                                                                       'whole text '
                                                                                       'so far); '
                                                                                       'only later '
                                                                                       'lines are '
                                                                                       'returned.',
                                                                        'default': -1,
                                                                        'minimum': -1},
                                                              'run': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'The run '
                                                                                     'value of the '
                                                                                     'previous '
                                                                                     'response; a '
                                                                                     'different '
                                                                                     'run means '
                                                                                     'the '
                                                                                     'recording '
                                                                                     'restarted '
                                                                                     'and the full '
                                                                                     'text is '
                                                                                     'returned '
                                                                                     'with '
                                                                                     'reset=true.'}},
                                               'live': True},
                     'event_questions': {'name': 'event_questions',
                                         'path': '/investor-events/{eventId}/questions',
                                         'parameters': {'eventId': {'location': 'path',
                                                                    'required': True,
                                                                    'type': 'string',
                                                                    'description': 'Investor event '
                                                                                   'id from the '
                                                                                   'investor-events '
                                                                                   'list.',
                                                                    'format': 'uuid'}},
                                         'live': False},
                     'event_slides': {'name': 'event_slides',
                                      'path': '/investor-events/{eventId}/slides',
                                      'parameters': {'eventId': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'Investor event id '
                                                                                'from the '
                                                                                'investor-events '
                                                                                'list.',
                                                                 'format': 'uuid'}},
                                      'live': False},
                     'event_speakers': {'name': 'event_speakers',
                                        'path': '/investor-events/{eventId}/speakers',
                                        'parameters': {'eventId': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': 'Investor event '
                                                                                  'id from the '
                                                                                  'investor-events '
                                                                                  'list.',
                                                                   'format': 'uuid'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum speaker '
                                                                                'turns to return '
                                                                                '(default 50, max '
                                                                                '200; zero or '
                                                                                'negative values '
                                                                                'are rejected, '
                                                                                'values above the '
                                                                                'maximum are '
                                                                                'clamped).',
                                                                 'minimum': 1,
                                                                 'maximum': 200},
                                                       'offset': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Speaker turns to '
                                                                                 'skip before the '
                                                                                 'first returned '
                                                                                 'one (default 0) '
                                                                                 '; pages past the '
                                                                                 'per-request '
                                                                                 'cap.'}},
                                        'live': False},
                     'ipos': {'name': 'ipos',
                              'path': '/ipos',
                              'parameters': {'status': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'Optional lifecycle filter: '
                                                                       'Filed, Priced, Listed, or '
                                                                       'Withdrawn.'},
                                             'filerType': {'location': 'query',
                                                           'required': False,
                                                           'type': 'string',
                                                           'description': 'Optional company-type '
                                                                          'filter: Operating '
                                                                          '(non-SPAC) or Spac (a '
                                                                          'blank-check company: '
                                                                          'SIC 6770, as SEC '
                                                                          'classifies the filer '
                                                                          'or, until it does, as '
                                                                          'its registration '
                                                                          'statement states).'},
                                             'limit': {'location': 'query',
                                                       'required': False,
                                                       'type': 'integer',
                                                       'description': 'Maximum rows to return '
                                                                      '(1–500; default varies per '
                                                                      'endpoint).',
                                                       'minimum': 1,
                                                       'maximum': 500},
                                             'offset': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Rows to skip before the '
                                                                       'first returned row '
                                                                       '(default 0).'}},
                              'live': False},
                     'ipo_detail': {'name': 'ipo_detail',
                                    'path': '/ipos/{cik}',
                                    'parameters': {'cik': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': "The filer's SEC CIK, "
                                                                          'with or without leading '
                                                                          'zeros.'}},
                                    'live': False},
                     'call_insights': {'name': 'call_insights',
                                       'path': '/stocks/{ticker}/call-insights',
                                       'parameters': {'ticker': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'Company ticker '
                                                                                'symbol (e.g. '
                                                                                'AAPL), or '
                                                                                'MIC:TICKER for a '
                                                                                'company listed on '
                                                                                'another exchange '
                                                                                '(e.g. XLIS:NOS).'},
                                                      'limit': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Maximum scored '
                                                                               'calls to return '
                                                                               '(default 2, max 8; '
                                                                               'zero or negative '
                                                                               'values are '
                                                                               'rejected, values '
                                                                               'above the maximum '
                                                                               'are clamped).',
                                                                'minimum': 1,
                                                                'maximum': 8},
                                                      'fiscalYear': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Optional '
                                                                                    'fiscal year, '
                                                                                    'in the '
                                                                                    "company's own "
                                                                                    'fiscal '
                                                                                    'calendar, to '
                                                                                    'fetch a '
                                                                                    'specific '
                                                                                    "period's "
                                                                                    'insights '
                                                                                    '(default: '
                                                                                    'newest '
                                                                                    'first).'},
                                                      'fiscalQuarter': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': 'Optional '
                                                                                       'fiscal '
                                                                                       'quarter, '
                                                                                       '1-4, to '
                                                                                       'fetch a '
                                                                                       'specific '
                                                                                       "period's "
                                                                                       'insights '
                                                                                       '(default: '
                                                                                       'newest '
                                                                                       'first).',
                                                                        'minimum': 1,
                                                                        'maximum': 4}},
                                       'live': False},
                     'call_themes': {'name': 'call_themes',
                                     'path': '/stocks/{ticker}/call-themes/history',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Company ticker '
                                                                              'symbol (e.g. AAPL), '
                                                                              'or MIC:TICKER for a '
                                                                              'company listed on '
                                                                              'another exchange '
                                                                              '(e.g. XLIS:NOS).'},
                                                    'calls': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Most recent scored '
                                                                             'fiscal quarters to '
                                                                             'compare (default 8, '
                                                                             'max 12; zero or '
                                                                             'negative values are '
                                                                             'rejected, values '
                                                                             'above the maximum '
                                                                             'are clamped).',
                                                              'maximum': 12}},
                                     'live': False},
                     'earnings_briefs': {'name': 'earnings_briefs',
                                         'path': '/stocks/{ticker}/earnings-briefs',
                                         'parameters': {'ticker': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': 'Company ticker '
                                                                                  'symbol (e.g. '
                                                                                  'AAPL), or '
                                                                                  'MIC:TICKER for '
                                                                                  'a company '
                                                                                  'listed on '
                                                                                  'another '
                                                                                  'exchange (e.g. '
                                                                                  'XLIS:NOS).'},
                                                        'limit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Maximum '
                                                                                 'quarterly briefs '
                                                                                 'to return '
                                                                                 '(default 2, max '
                                                                                 '8; zero or '
                                                                                 'negative values '
                                                                                 'are rejected, '
                                                                                 'values above the '
                                                                                 'maximum are '
                                                                                 'clamped).',
                                                                  'minimum': 1,
                                                                  'maximum': 8},
                                                        'fiscalYear': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': 'Optional '
                                                                                      'fiscal '
                                                                                      'year, in '
                                                                                      'the '
                                                                                      "company's "
                                                                                      'own fiscal '
                                                                                      'calendar, '
                                                                                      'to fetch a '
                                                                                      'specific '
                                                                                      "period's "
                                                                                      'brief '
                                                                                      '(default: '
                                                                                      'newest '
                                                                                      'first).'},
                                                        'fiscalQuarter': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'integer',
                                                                          'description': 'Optional '
                                                                                         'fiscal '
                                                                                         'quarter, '
                                                                                         '1-4, to '
                                                                                         'fetch a '
                                                                                         'specific '
                                                                                         "period's "
                                                                                         'brief '
                                                                                         '(default: '
                                                                                         'newest '
                                                                                         'first).',
                                                                          'minimum': 1,
                                                                          'maximum': 4}},
                                         'live': False},
                     'earnings_call_phrase_trend': {'name': 'earnings_call_phrase_trend',
                                                    'path': '/stocks/{ticker}/earnings-calls/phrase-trend',
                                                    'parameters': {'ticker': {'location': 'path',
                                                                              'required': True,
                                                                              'type': 'string',
                                                                              'description': 'Company '
                                                                                             'ticker '
                                                                                             'symbol '
                                                                                             '(e.g. '
                                                                                             'AAPL), '
                                                                                             'or '
                                                                                             'MIC:TICKER '
                                                                                             'for '
                                                                                             'a '
                                                                                             'company '
                                                                                             'listed '
                                                                                             'on '
                                                                                             'another '
                                                                                             'exchange '
                                                                                             '(e.g. '
                                                                                             'XLIS:NOS).'},
                                                                   'phrase': {'location': 'query',
                                                                              'required': True,
                                                                              'type': 'string',
                                                                              'description': 'Required. '
                                                                                             'Word '
                                                                                             'or '
                                                                                             'phrase '
                                                                                             'to '
                                                                                             'count, '
                                                                                             '2-80 '
                                                                                             'characters '
                                                                                             'after '
                                                                                             'trimming '
                                                                                             '(e.g. '
                                                                                             'tariffs, '
                                                                                             'sovereign '
                                                                                             'AI); '
                                                                                             'a '
                                                                                             'space '
                                                                                             'matches '
                                                                                             'any '
                                                                                             'whitespace.'},
                                                                   'calls': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'integer',
                                                                             'description': 'Most '
                                                                                            'recent '
                                                                                            'earnings '
                                                                                            'calls '
                                                                                            'to '
                                                                                            'read '
                                                                                            '(default '
                                                                                            '8, '
                                                                                            'max '
                                                                                            '12; '
                                                                                            'zero '
                                                                                            'or '
                                                                                            'negative '
                                                                                            'values '
                                                                                            'are '
                                                                                            'rejected, '
                                                                                            'values '
                                                                                            'above '
                                                                                            'the '
                                                                                            'maximum '
                                                                                            'are '
                                                                                            'clamped).',
                                                                             'maximum': 12}},
                                                    'live': False},
                     'earnings_call': {'name': 'earnings_call',
                                       'path': '/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}',
                                       'parameters': {'ticker': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'Company ticker '
                                                                                'symbol (e.g. '
                                                                                'AAPL), or '
                                                                                'MIC:TICKER for a '
                                                                                'company listed on '
                                                                                'another exchange '
                                                                                '(e.g. XLIS:NOS).'},
                                                      'fiscalYear': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'integer',
                                                                     'description': 'Fiscal year '
                                                                                    'the quarter '
                                                                                    'belongs to '
                                                                                    '(e.g. 2025).'},
                                                      'fiscalQuarter': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'integer',
                                                                        'description': 'Fiscal '
                                                                                       'quarter, '
                                                                                       '1-4.',
                                                                        'minimum': 1,
                                                                        'maximum': 4}},
                                       'live': False},
                     'earnings_call_live_transcript': {'name': 'earnings_call_live_transcript',
                                                       'path': '/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/live-transcript',
                                                       'parameters': {'ticker': {'location': 'path',
                                                                                 'required': True,
                                                                                 'type': 'string',
                                                                                 'description': 'Company '
                                                                                                'ticker '
                                                                                                'symbol '
                                                                                                '(e.g. '
                                                                                                'AAPL), '
                                                                                                'or '
                                                                                                'MIC:TICKER '
                                                                                                'for '
                                                                                                'a '
                                                                                                'company '
                                                                                                'listed '
                                                                                                'on '
                                                                                                'another '
                                                                                                'exchange '
                                                                                                '(e.g. '
                                                                                                'XLIS:NOS).'},
                                                                      'fiscalYear': {'location': 'path',
                                                                                     'required': True,
                                                                                     'type': 'integer',
                                                                                     'description': 'Fiscal '
                                                                                                    'year '
                                                                                                    'the '
                                                                                                    'quarter '
                                                                                                    'belongs '
                                                                                                    'to '
                                                                                                    '(e.g. '
                                                                                                    '2025).'},
                                                                      'fiscalQuarter': {'location': 'path',
                                                                                        'required': True,
                                                                                        'type': 'integer',
                                                                                        'description': 'Fiscal '
                                                                                                       'quarter, '
                                                                                                       '1-4.',
                                                                                        'minimum': 1,
                                                                                        'maximum': 4},
                                                                      'after': {'location': 'query',
                                                                                'required': False,
                                                                                'type': 'integer',
                                                                                'description': 'The '
                                                                                               'highest '
                                                                                               'line '
                                                                                               'seq '
                                                                                               'already '
                                                                                               'received '
                                                                                               '(default '
                                                                                               '-1, '
                                                                                               'the '
                                                                                               'whole '
                                                                                               'text '
                                                                                               'so '
                                                                                               'far); '
                                                                                               'only '
                                                                                               'later '
                                                                                               'lines '
                                                                                               'are '
                                                                                               'returned.',
                                                                                'default': -1,
                                                                                'minimum': -1},
                                                                      'run': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'string',
                                                                              'description': 'The '
                                                                                             'run '
                                                                                             'value '
                                                                                             'of '
                                                                                             'the '
                                                                                             'previous '
                                                                                             'response; '
                                                                                             'a '
                                                                                             'different '
                                                                                             'run '
                                                                                             'means '
                                                                                             'the '
                                                                                             'recording '
                                                                                             'restarted '
                                                                                             'and '
                                                                                             'the '
                                                                                             'full '
                                                                                             'text '
                                                                                             'is '
                                                                                             'returned '
                                                                                             'with '
                                                                                             'reset=true.'}},
                                                       'live': True},
                     'earnings_call_questions': {'name': 'earnings_call_questions',
                                                 'path': '/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/questions',
                                                 'parameters': {'ticker': {'location': 'path',
                                                                           'required': True,
                                                                           'type': 'string',
                                                                           'description': 'Company '
                                                                                          'ticker '
                                                                                          'symbol '
                                                                                          '(e.g. '
                                                                                          'AAPL), '
                                                                                          'or '
                                                                                          'MIC:TICKER '
                                                                                          'for a '
                                                                                          'company '
                                                                                          'listed '
                                                                                          'on '
                                                                                          'another '
                                                                                          'exchange '
                                                                                          '(e.g. '
                                                                                          'XLIS:NOS).'},
                                                                'fiscalYear': {'location': 'path',
                                                                               'required': True,
                                                                               'type': 'integer',
                                                                               'description': 'Fiscal '
                                                                                              'year '
                                                                                              'the '
                                                                                              'quarter '
                                                                                              'belongs '
                                                                                              'to '
                                                                                              '(e.g. '
                                                                                              '2025).'},
                                                                'fiscalQuarter': {'location': 'path',
                                                                                  'required': True,
                                                                                  'type': 'integer',
                                                                                  'description': 'Fiscal '
                                                                                                 'quarter, '
                                                                                                 '1-4.',
                                                                                  'minimum': 1,
                                                                                  'maximum': 4}},
                                                 'live': False},
                     'earnings_call_speakers': {'name': 'earnings_call_speakers',
                                                'path': '/stocks/{ticker}/earnings-calls/{fiscalYear}/{fiscalQuarter}/speakers',
                                                'parameters': {'ticker': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'string',
                                                                          'description': 'Company '
                                                                                         'ticker '
                                                                                         'symbol '
                                                                                         '(e.g. '
                                                                                         'AAPL), '
                                                                                         'or '
                                                                                         'MIC:TICKER '
                                                                                         'for a '
                                                                                         'company '
                                                                                         'listed '
                                                                                         'on '
                                                                                         'another '
                                                                                         'exchange '
                                                                                         '(e.g. '
                                                                                         'XLIS:NOS).'},
                                                               'fiscalYear': {'location': 'path',
                                                                              'required': True,
                                                                              'type': 'integer',
                                                                              'description': 'Fiscal '
                                                                                             'year '
                                                                                             'the '
                                                                                             'quarter '
                                                                                             'belongs '
                                                                                             'to '
                                                                                             '(e.g. '
                                                                                             '2025).'},
                                                               'fiscalQuarter': {'location': 'path',
                                                                                 'required': True,
                                                                                 'type': 'integer',
                                                                                 'description': 'Fiscal '
                                                                                                'quarter, '
                                                                                                '1-4.',
                                                                                 'minimum': 1,
                                                                                 'maximum': 4},
                                                               'limit': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Maximum '
                                                                                        'speaker '
                                                                                        'turns to '
                                                                                        'return '
                                                                                        '(default '
                                                                                        '50, max '
                                                                                        '200; zero '
                                                                                        'or '
                                                                                        'negative '
                                                                                        'values '
                                                                                        'are '
                                                                                        'rejected, '
                                                                                        'values '
                                                                                        'above the '
                                                                                        'maximum '
                                                                                        'are '
                                                                                        'clamped).',
                                                                         'minimum': 1,
                                                                         'maximum': 200},
                                                               'offset': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'integer',
                                                                          'description': 'Speaker '
                                                                                         'turns to '
                                                                                         'skip '
                                                                                         'before '
                                                                                         'the '
                                                                                         'first '
                                                                                         'returned '
                                                                                         'one '
                                                                                         '(default '
                                                                                         '0) ; '
                                                                                         'pages '
                                                                                         'past the '
                                                                                         'per-request '
                                                                                         'cap.'}},
                                                'live': False},
                     'investor_events': {'name': 'investor_events',
                                         'path': '/stocks/{ticker}/investor-events',
                                         'parameters': {'ticker': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': 'Company ticker '
                                                                                  'symbol (e.g. '
                                                                                  'AAPL), or '
                                                                                  'MIC:TICKER for '
                                                                                  'a company '
                                                                                  'listed on '
                                                                                  'another '
                                                                                  'exchange (e.g. '
                                                                                  'XLIS:NOS).'},
                                                        'limit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Maximum rows to '
                                                                                 'return (1–500; '
                                                                                 'default varies '
                                                                                 'per endpoint).',
                                                                  'minimum': 1,
                                                                  'maximum': 500},
                                                        'offset': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Rows to skip '
                                                                                  'before the '
                                                                                  'first returned '
                                                                                  'row (default '
                                                                                  '0).'},
                                                        'eventType': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'Optional '
                                                                                     'event type: '
                                                                                     'EarningsCall, '
                                                                                     'CapitalMarketsDay, '
                                                                                     'InvestorUpdate, '
                                                                                     'AGM, '
                                                                                     'Conference, '
                                                                                     'FiresideChat, '
                                                                                     'or MAndA.'},
                                                        'includeUncaptured': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'boolean',
                                                                              'description': 'Also '
                                                                                             'return '
                                                                                             'events '
                                                                                             'hidden '
                                                                                             'because '
                                                                                             'none '
                                                                                             'of '
                                                                                             'their '
                                                                                             'materials '
                                                                                             'could '
                                                                                             'be '
                                                                                             'captured '
                                                                                             'and '
                                                                                             'still '
                                                                                             'on '
                                                                                             'the '
                                                                                             "company's "
                                                                                             'own '
                                                                                             'IR '
                                                                                             'calendar '
                                                                                             '(default '
                                                                                             'false); '
                                                                                             'such '
                                                                                             'rows '
                                                                                             'carry '
                                                                                             'isTombstoned=true.',
                                                                              'default': False}},
                                         'live': False},
                     'ir_events': {'name': 'ir_events',
                                   'path': '/stocks/{ticker}/ir-events',
                                   'parameters': {'ticker': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'Company ticker symbol '
                                                                            '(e.g. AAPL), or '
                                                                            'MIC:TICKER for a '
                                                                            'company listed on '
                                                                            'another exchange '
                                                                            '(e.g. XLIS:NOS).'},
                                                  'limit': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Maximum events to '
                                                                           'return (default 20, '
                                                                           'max 500; zero or '
                                                                           'negative values are '
                                                                           'rejected, values above '
                                                                           'the maximum are '
                                                                           'clamped).',
                                                            'minimum': 1,
                                                            'maximum': 500},
                                                  'eventType': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'Optional event '
                                                                               'type: '
                                                                               'EarningsCall, '
                                                                               'Conference, '
                                                                               'Presentation, '
                                                                               'ShareholderMeeting, '
                                                                               'or Webcast.'}},
                                   'live': False},
                     'ir_news': {'name': 'ir_news',
                                 'path': '/stocks/{ticker}/ir-news',
                                 'parameters': {'ticker': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': 'Company ticker symbol '
                                                                          '(e.g. AAPL), or '
                                                                          'MIC:TICKER for a '
                                                                          'company listed on '
                                                                          'another exchange (e.g. '
                                                                          'XLIS:NOS).'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum rows to return '
                                                                         '(1–500; default varies '
                                                                         'per endpoint).',
                                                          'minimum': 1,
                                                          'maximum': 500},
                                                'offset': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Rows to skip before the '
                                                                          'first returned row '
                                                                          '(default 0).'},
                                                'since': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Only include releases '
                                                                         'published on or after '
                                                                         'this date (yyyy-MM-dd).',
                                                          'format': 'date'}},
                                 'live': False}},
 'market_data': {'security_bars': {'name': 'security_bars',
                                   'path': '/securities/{ticker}/bars',
                                   'parameters': {'ticker': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'Exact listed US '
                                                                            'ticker (e.g. GOOG, '
                                                                            'GOOGL, BRK-A, or '
                                                                            'BRK-B), or '
                                                                            '`MIC:TICKER` for a '
                                                                            'Euronext, Canadian or '
                                                                            'NSE listing (e.g. '
                                                                            'XPAR:AIR, XTSE:RY or '
                                                                            'XNSE:RELIANCE). A '
                                                                            'listing never falls '
                                                                            'through to its '
                                                                            'sibling; dot '
                                                                            'class-share spelling '
                                                                            'such as BRK.B is '
                                                                            'accepted as BRK-B.'},
                                                  'interval': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Bar size: a whole '
                                                                              'number of minutes '
                                                                              'from 1min (default) '
                                                                              'to 240min, such as '
                                                                              '5min or 7min, or of '
                                                                              'hours from 1hour to '
                                                                              '4hour. The answer '
                                                                              'echoes whole hours '
                                                                              'in hours (60min as '
                                                                              '1hour).'},
                                                  'startDate': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'First trading date '
                                                                               "on the exchange's "
                                                                               'own clock (New '
                                                                               'York for a US '
                                                                               'listing), '
                                                                               'YYYY-MM-DD '
                                                                               '(default: 7 days '
                                                                               'before the end, 30 '
                                                                               'for hourly '
                                                                               'intervals).',
                                                                'format': 'date'},
                                                  'endDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Last trading date on '
                                                                             "the exchange's own "
                                                                             'clock, YYYY-MM-DD '
                                                                             '(default: today).',
                                                              'format': 'date'},
                                                  'endTime': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Return only bars '
                                                                             'that start before '
                                                                             'this RFC 3339 time; '
                                                                             'replaces endDate. '
                                                                             'Pass the oldest '
                                                                             "bar's time to "
                                                                             'continue a truncated '
                                                                             'read, and keep '
                                                                             'startDate: without '
                                                                             'it the window is '
                                                                             'counted back again '
                                                                             'from this time.',
                                                              'format': 'timestamp'},
                                                  'session': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'regular (default) or '
                                                                             'extended.'},
                                                  'adjustment': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'split (default) '
                                                                                'or raw.'},
                                                  'limit': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Maximum bars to '
                                                                           'return, newest first '
                                                                           '(default: 250, max: '
                                                                           '500; with format=csv '
                                                                           'default and max '
                                                                           '50,000, at one call '
                                                                           'for each 500 bars '
                                                                           'returned).',
                                                            'minimum': 1,
                                                            'maximum': 500},
                                                  'format': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Omit or json for the '
                                                                            'JSON envelope, csv '
                                                                            'for a flat file with '
                                                                            'one row a bar under '
                                                                            'the JSON field names. '
                                                                            'A file costs one call '
                                                                            'for each 500 bars it '
                                                                            'returns, stated on '
                                                                            'X-Bars-Calls; one '
                                                                            'that needs more calls '
                                                                            'than the day has left '
                                                                            'answers 429 and names '
                                                                            'the limit that fits. '
                                                                            "The envelope's fields "
                                                                            'ride on the '
                                                                            'X-Bars-Returned, '
                                                                            'X-Bars-Truncated, '
                                                                            'X-Bars-Delayed, '
                                                                            'X-Bars-Covered-From '
                                                                            'and '
                                                                            'X-Bars-Adjusted-From '
                                                                            'response headers, '
                                                                            'plus X-Bars-Currency '
                                                                            'and '
                                                                            'X-Bars-Stored-Through '
                                                                            'for a listing outside '
                                                                            'the US, '
                                                                            'X-Bars-Incomplete-Sessions '
                                                                            'and '
                                                                            'X-Bars-Unstored-Dates '
                                                                            'for a Euronext '
                                                                            'listing and '
                                                                            'X-Bars-Notice for a '
                                                                            'Canadian one.'}},
                                   'live': False,
                                   'json_only': True},
                 'security_prices': {'name': 'security_prices',
                                     'path': '/securities/{ticker}/prices',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Exact listed ticker '
                                                                              '(e.g. GOOG, GOOGL, '
                                                                              'BRK-A, or BRK-B), '
                                                                              'or MIC:TICKER for a '
                                                                              'listing on another '
                                                                              'exchange (e.g. '
                                                                              'XETR:SIE or '
                                                                              'XLON:BP). Each '
                                                                              'listing has an '
                                                                              'independent price '
                                                                              'series; dot '
                                                                              'class-share '
                                                                              'spelling such as '
                                                                              'BRK.B is accepted '
                                                                              'as BRK-B.'},
                                                    'startDate': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Start date '
                                                                                 '(yyyy-MM-dd, '
                                                                                 'defaults to 1 '
                                                                                 'year ago).',
                                                                  'format': 'date'},
                                                    'endDate': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'End date '
                                                                               '(yyyy-MM-dd, '
                                                                               'defaults to '
                                                                               'today).',
                                                                'format': 'date'},
                                                    'limit': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Maximum rows to '
                                                                             'return (1–500; '
                                                                             'default varies per '
                                                                             'endpoint).',
                                                              'minimum': 1,
                                                              'maximum': 500},
                                                    'offset': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': 'Rows to skip before '
                                                                              'the first returned '
                                                                              'row (default 0).'},
                                                    'interval': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'daily (default), '
                                                                                'weekly or '
                                                                                'monthly. Weekly '
                                                                                '(ISO week) and '
                                                                                'monthly bars roll '
                                                                                'up the daily '
                                                                                'bars: first open, '
                                                                                'highest high, '
                                                                                'lowest low, last '
                                                                                'close and '
                                                                                'adjusted close, '
                                                                                'summed volume, '
                                                                                'dated by their '
                                                                                'last session, '
                                                                                'with periodStart '
                                                                                'and partial '
                                                                                'set.'}},
                                     'live': False},
                 'security_quote': {'name': 'security_quote',
                                    'path': '/securities/{ticker}/quote',
                                    'parameters': {'ticker': {'location': 'path',
                                                              'required': True,
                                                              'type': 'string',
                                                              'description': 'Exact listed ticker '
                                                                             '(e.g. GOOG, GOOGL, '
                                                                             'BRK-A, or BRK-B), or '
                                                                             'MIC:TICKER for a '
                                                                             'Canadian, Euronext '
                                                                             'or NSE listing (e.g. '
                                                                             'XTSE:RY, XPAR:AIR or '
                                                                             'XNSE:RELIANCE). A '
                                                                             'missing listing is '
                                                                             'never replaced by '
                                                                             'its sibling; dot '
                                                                             'class-share spelling '
                                                                             'such as BRK.B is '
                                                                             'accepted as BRK-B.'}},
                                    'live': False},
                 'security_technicals_atr': {'name': 'security_technicals_atr',
                                             'path': '/securities/{ticker}/technicals/atr',
                                             'parameters': {'ticker': {'location': 'path',
                                                                       'required': True,
                                                                       'type': 'string',
                                                                       'description': 'Exact '
                                                                                      'listed '
                                                                                      'ticker '
                                                                                      '(e.g. GOOG '
                                                                                      'or GOOGL), '
                                                                                      'or '
                                                                                      'MIC:TICKER '
                                                                                      'for a '
                                                                                      'listing on '
                                                                                      'another '
                                                                                      'exchange '
                                                                                      '(e.g. '
                                                                                      'XETR:SIE), '
                                                                                      'computed in '
                                                                                      'its trading '
                                                                                      'currency in '
                                                                                      'major '
                                                                                      'units. Each '
                                                                                      'listing '
                                                                                      'uses its '
                                                                                      'own bars; '
                                                                                      'dot '
                                                                                      'class-share '
                                                                                      'spelling '
                                                                                      'such as '
                                                                                      'BRK.B is '
                                                                                      'accepted as '
                                                                                      'BRK-B.'},
                                                            'startDate': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': 'Start '
                                                                                         'date '
                                                                                         '(yyyy-MM-dd, '
                                                                                         'defaults '
                                                                                         'to 6 '
                                                                                         'months '
                                                                                         'ago).',
                                                                          'format': 'date'},
                                                            'endDate': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': 'End date '
                                                                                       '(yyyy-MM-dd, '
                                                                                       'defaults '
                                                                                       'to today).',
                                                                        'format': 'date'},
                                                            'period': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': 'Lookback '
                                                                                      'period '
                                                                                      '(default '
                                                                                      '14, minimum '
                                                                                      '2).',
                                                                       'default': 14,
                                                                       'minimum': 2},
                                                            'limit': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': 'Most recent '
                                                                                     'points to '
                                                                                     'return '
                                                                                     '(default 60, '
                                                                                     'max 500).',
                                                                      'minimum': 1,
                                                                      'maximum': 500}},
                                             'live': False},
                 'security_technicals_bollinger_bands': {'name': 'security_technicals_bollinger_bands',
                                                         'path': '/securities/{ticker}/technicals/bollinger-bands',
                                                         'parameters': {'ticker': {'location': 'path',
                                                                                   'required': True,
                                                                                   'type': 'string',
                                                                                   'description': 'Exact '
                                                                                                  'listed '
                                                                                                  'ticker '
                                                                                                  '(e.g. '
                                                                                                  'GOOG '
                                                                                                  'or '
                                                                                                  'GOOGL), '
                                                                                                  'or '
                                                                                                  'MIC:TICKER '
                                                                                                  'for '
                                                                                                  'a '
                                                                                                  'listing '
                                                                                                  'on '
                                                                                                  'another '
                                                                                                  'exchange '
                                                                                                  '(e.g. '
                                                                                                  'XETR:SIE), '
                                                                                                  'computed '
                                                                                                  'in '
                                                                                                  'its '
                                                                                                  'trading '
                                                                                                  'currency '
                                                                                                  'in '
                                                                                                  'major '
                                                                                                  'units. '
                                                                                                  'Each '
                                                                                                  'listing '
                                                                                                  'uses '
                                                                                                  'its '
                                                                                                  'own '
                                                                                                  'bars; '
                                                                                                  'dot '
                                                                                                  'class-share '
                                                                                                  'spelling '
                                                                                                  'such '
                                                                                                  'as '
                                                                                                  'BRK.B '
                                                                                                  'is '
                                                                                                  'accepted '
                                                                                                  'as '
                                                                                                  'BRK-B.'},
                                                                        'startDate': {'location': 'query',
                                                                                      'required': False,
                                                                                      'type': 'string',
                                                                                      'description': 'Start '
                                                                                                     'date '
                                                                                                     '(yyyy-MM-dd, '
                                                                                                     'defaults '
                                                                                                     'to '
                                                                                                     '6 '
                                                                                                     'months '
                                                                                                     'ago).',
                                                                                      'format': 'date'},
                                                                        'endDate': {'location': 'query',
                                                                                    'required': False,
                                                                                    'type': 'string',
                                                                                    'description': 'End '
                                                                                                   'date '
                                                                                                   '(yyyy-MM-dd, '
                                                                                                   'defaults '
                                                                                                   'to '
                                                                                                   'today).',
                                                                                    'format': 'date'},
                                                                        'period': {'location': 'query',
                                                                                   'required': False,
                                                                                   'type': 'integer',
                                                                                   'description': 'Moving-average '
                                                                                                  'period '
                                                                                                  '(default '
                                                                                                  '20, '
                                                                                                  'minimum '
                                                                                                  '2).',
                                                                                   'default': 20,
                                                                                   'minimum': 2},
                                                                        'stdDev': {'location': 'query',
                                                                                   'required': False,
                                                                                   'type': 'number',
                                                                                   'description': 'Standard-deviation '
                                                                                                  'multiple '
                                                                                                  'for '
                                                                                                  'the '
                                                                                                  'bands '
                                                                                                  '(default '
                                                                                                  '2, '
                                                                                                  'must '
                                                                                                  'be '
                                                                                                  'greater '
                                                                                                  'than '
                                                                                                  '0).',
                                                                                   'default': 2.0},
                                                                        'limit': {'location': 'query',
                                                                                  'required': False,
                                                                                  'type': 'integer',
                                                                                  'description': 'Most '
                                                                                                 'recent '
                                                                                                 'points '
                                                                                                 'to '
                                                                                                 'return '
                                                                                                 '(default '
                                                                                                 '60, '
                                                                                                 'max '
                                                                                                 '500).',
                                                                                  'minimum': 1,
                                                                                  'maximum': 500}},
                                                         'live': False},
                 'security_technicals_obv': {'name': 'security_technicals_obv',
                                             'path': '/securities/{ticker}/technicals/obv',
                                             'parameters': {'ticker': {'location': 'path',
                                                                       'required': True,
                                                                       'type': 'string',
                                                                       'description': 'Exact '
                                                                                      'listed '
                                                                                      'ticker '
                                                                                      '(e.g. GOOG '
                                                                                      'or GOOGL), '
                                                                                      'or '
                                                                                      'MIC:TICKER '
                                                                                      'for a '
                                                                                      'listing on '
                                                                                      'another '
                                                                                      'exchange '
                                                                                      '(e.g. '
                                                                                      'XETR:SIE), '
                                                                                      'computed in '
                                                                                      'its trading '
                                                                                      'currency in '
                                                                                      'major '
                                                                                      'units. Each '
                                                                                      'listing '
                                                                                      'uses its '
                                                                                      'own bars; '
                                                                                      'dot '
                                                                                      'class-share '
                                                                                      'spelling '
                                                                                      'such as '
                                                                                      'BRK.B is '
                                                                                      'accepted as '
                                                                                      'BRK-B.'},
                                                            'startDate': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': 'Start '
                                                                                         'date '
                                                                                         '(yyyy-MM-dd, '
                                                                                         'defaults '
                                                                                         'to 6 '
                                                                                         'months '
                                                                                         'ago).',
                                                                          'format': 'date'},
                                                            'endDate': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': 'End date '
                                                                                       '(yyyy-MM-dd, '
                                                                                       'defaults '
                                                                                       'to today).',
                                                                        'format': 'date'},
                                                            'limit': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': 'Most recent '
                                                                                     'points to '
                                                                                     'return '
                                                                                     '(default 60, '
                                                                                     'max 500).',
                                                                      'minimum': 1,
                                                                      'maximum': 500}},
                                             'live': False},
                 'security_technicals_stochastic': {'name': 'security_technicals_stochastic',
                                                    'path': '/securities/{ticker}/technicals/stochastic',
                                                    'parameters': {'ticker': {'location': 'path',
                                                                              'required': True,
                                                                              'type': 'string',
                                                                              'description': 'Exact '
                                                                                             'listed '
                                                                                             'ticker '
                                                                                             '(e.g. '
                                                                                             'GOOG '
                                                                                             'or '
                                                                                             'GOOGL), '
                                                                                             'or '
                                                                                             'MIC:TICKER '
                                                                                             'for '
                                                                                             'a '
                                                                                             'listing '
                                                                                             'on '
                                                                                             'another '
                                                                                             'exchange '
                                                                                             '(e.g. '
                                                                                             'XETR:SIE), '
                                                                                             'computed '
                                                                                             'in '
                                                                                             'its '
                                                                                             'trading '
                                                                                             'currency '
                                                                                             'in '
                                                                                             'major '
                                                                                             'units. '
                                                                                             'Each '
                                                                                             'listing '
                                                                                             'uses '
                                                                                             'its '
                                                                                             'own '
                                                                                             'bars; '
                                                                                             'dot '
                                                                                             'class-share '
                                                                                             'spelling '
                                                                                             'such '
                                                                                             'as '
                                                                                             'BRK.B '
                                                                                             'is '
                                                                                             'accepted '
                                                                                             'as '
                                                                                             'BRK-B.'},
                                                                   'startDate': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'string',
                                                                                 'description': 'Start '
                                                                                                'date '
                                                                                                '(yyyy-MM-dd, '
                                                                                                'defaults '
                                                                                                'to '
                                                                                                '6 '
                                                                                                'months '
                                                                                                'ago).',
                                                                                 'format': 'date'},
                                                                   'endDate': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'string',
                                                                               'description': 'End '
                                                                                              'date '
                                                                                              '(yyyy-MM-dd, '
                                                                                              'defaults '
                                                                                              'to '
                                                                                              'today).',
                                                                               'format': 'date'},
                                                                   'kPeriod': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'integer',
                                                                               'description': '%K '
                                                                                              'lookback '
                                                                                              'period '
                                                                                              '(default '
                                                                                              '14, '
                                                                                              'minimum '
                                                                                              '2).',
                                                                               'default': 14,
                                                                               'minimum': 2},
                                                                   'dPeriod': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'integer',
                                                                               'description': '%D '
                                                                                              'smoothing '
                                                                                              'period '
                                                                                              '(default '
                                                                                              '3, '
                                                                                              'minimum '
                                                                                              '1).',
                                                                               'default': 3,
                                                                               'minimum': 1},
                                                                   'limit': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'integer',
                                                                             'description': 'Most '
                                                                                            'recent '
                                                                                            'points '
                                                                                            'to '
                                                                                            'return '
                                                                                            '(default '
                                                                                            '60, '
                                                                                            'max '
                                                                                            '500).',
                                                                             'minimum': 1,
                                                                             'maximum': 500}},
                                                    'live': False},
                 'bars': {'name': 'bars',
                          'path': '/stocks/{ticker}/bars',
                          'parameters': {'ticker': {'location': 'path',
                                                    'required': True,
                                                    'type': 'string',
                                                    'description': 'Exact listed US ticker (e.g. '
                                                                   'GOOG, GOOGL, BRK-A, or BRK-B), '
                                                                   'or `MIC:TICKER` for a '
                                                                   'Euronext, Canadian or NSE '
                                                                   'listing (e.g. XPAR:AIR, '
                                                                   'XTSE:RY or XNSE:RELIANCE). A '
                                                                   'listing never falls through to '
                                                                   'its sibling; dot class-share '
                                                                   'spelling such as BRK.B is '
                                                                   'accepted as BRK-B.'},
                                         'interval': {'location': 'query',
                                                      'required': False,
                                                      'type': 'string',
                                                      'description': 'Bar size: a whole number of '
                                                                     'minutes from 1min (default) '
                                                                     'to 240min, such as 5min or '
                                                                     '7min, or of hours from 1hour '
                                                                     'to 4hour. The answer echoes '
                                                                     'whole hours in hours (60min '
                                                                     'as 1hour).'},
                                         'startDate': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'First trading date on the '
                                                                      "exchange's own clock (New "
                                                                      'York for a US listing), '
                                                                      'YYYY-MM-DD (default: 7 days '
                                                                      'before the end, 30 for '
                                                                      'hourly intervals).',
                                                       'format': 'date'},
                                         'endDate': {'location': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'Last trading date on the '
                                                                    "exchange's own clock, "
                                                                    'YYYY-MM-DD (default: today).',
                                                     'format': 'date'},
                                         'endTime': {'location': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'Return only bars that start '
                                                                    'before this RFC 3339 time; '
                                                                    'replaces endDate. Pass the '
                                                                    "oldest bar's time to continue "
                                                                    'a truncated read, and keep '
                                                                    'startDate: without it the '
                                                                    'window is counted back again '
                                                                    'from this time.',
                                                     'format': 'timestamp'},
                                         'session': {'location': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'regular (default) or '
                                                                    'extended.'},
                                         'adjustment': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'split (default) or raw.'},
                                         'limit': {'location': 'query',
                                                   'required': False,
                                                   'type': 'integer',
                                                   'description': 'Maximum bars to return, newest '
                                                                  'first (default: 250, max: 500; '
                                                                  'with format=csv default and max '
                                                                  '50,000, at one call for each '
                                                                  '500 bars returned).',
                                                   'minimum': 1,
                                                   'maximum': 500},
                                         'format': {'location': 'query',
                                                    'required': False,
                                                    'type': 'string',
                                                    'description': 'Omit or json for the JSON '
                                                                   'envelope, csv for a flat file '
                                                                   'with one row a bar under the '
                                                                   'JSON field names. A file costs '
                                                                   'one call for each 500 bars it '
                                                                   'returns, stated on '
                                                                   'X-Bars-Calls; one that needs '
                                                                   'more calls than the day has '
                                                                   'left answers 429 and names the '
                                                                   'limit that fits. The '
                                                                   "envelope's fields ride on the "
                                                                   'X-Bars-Returned, '
                                                                   'X-Bars-Truncated, '
                                                                   'X-Bars-Delayed, '
                                                                   'X-Bars-Covered-From and '
                                                                   'X-Bars-Adjusted-From response '
                                                                   'headers, plus X-Bars-Currency '
                                                                   'and X-Bars-Stored-Through for '
                                                                   'a listing outside the US, '
                                                                   'X-Bars-Incomplete-Sessions and '
                                                                   'X-Bars-Unstored-Dates for a '
                                                                   'Euronext listing and '
                                                                   'X-Bars-Notice for a Canadian '
                                                                   'one.'}},
                          'live': False,
                          'json_only': True},
                 'correlated': {'name': 'correlated',
                                'path': '/stocks/{ticker}/correlated',
                                'parameters': {'ticker': {'location': 'path',
                                                          'required': True,
                                                          'type': 'string',
                                                          'description': 'Exact listed ticker '
                                                                         '(e.g. GOOG or GOOGL). '
                                                                         "The requested listing's "
                                                                         'own daily series is the '
                                                                         'correlation subject; dot '
                                                                         'class-share spelling '
                                                                         'such as BRK.B is '
                                                                         'accepted as BRK-B.'},
                                               'scope': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'Candidate universe: '
                                                                        'Industry (default), '
                                                                        'Sector, or Market (~1,500 '
                                                                        'largest listed names).',
                                                         'default': 'Industry'},
                                               'days': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Trailing calendar window '
                                                                       'in days for the return '
                                                                       'series (default 180, '
                                                                       'clamped to 30-730).',
                                                        'default': 180,
                                                        'minimum': 30,
                                                        'maximum': 730},
                                               'direction': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Positive (default) '
                                                                            'for the strongest '
                                                                            'co-movers, Negative '
                                                                            'for the strongest '
                                                                            'inverse movers.',
                                                             'default': 'Positive'},
                                               'limit': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Maximum number of stocks '
                                                                        'to return (default 10, '
                                                                        'max 50).',
                                                         'default': 10,
                                                         'minimum': 1,
                                                         'maximum': 50}},
                                'live': False},
                 'dividends': {'name': 'dividends',
                               'path': '/stocks/{ticker}/dividends',
                               'parameters': {'ticker': {'location': 'path',
                                                         'required': True,
                                                         'type': 'string',
                                                         'description': 'Listed stock or ETF '
                                                                        'ticker (e.g. AAPL, BRK.A, '
                                                                        'SCHD), or MIC:TICKER for '
                                                                        'a listing on another '
                                                                        'exchange (e.g. '
                                                                        'XETR:SIE).'},
                                              'startDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Earliest ex-dividend '
                                                                           'date (yyyy-MM-dd).',
                                                            'format': 'date'},
                                              'endDate': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Latest ex-dividend date '
                                                                         '(yyyy-MM-dd).',
                                                          'format': 'date'},
                                              'limit': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Maximum rows to return '
                                                                       '(1–500; default varies per '
                                                                       'endpoint).',
                                                        'minimum': 1,
                                                        'maximum': 500},
                                              'offset': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Rows to skip before the '
                                                                        'first returned row '
                                                                        '(default 0).'}},
                               'live': False},
                 'prices': {'name': 'prices',
                            'path': '/stocks/{ticker}/prices',
                            'parameters': {'ticker': {'location': 'path',
                                                      'required': True,
                                                      'type': 'string',
                                                      'description': 'Exact listed ticker (e.g. '
                                                                     'GOOG, GOOGL, BRK-A, or '
                                                                     'BRK-B), or MIC:TICKER for a '
                                                                     'listing on another exchange '
                                                                     '(e.g. XETR:SIE or XLON:BP). '
                                                                     'Each listing has an '
                                                                     'independent price series; '
                                                                     'dot class-share spelling '
                                                                     'such as BRK.B is accepted as '
                                                                     'BRK-B.'},
                                           'startDate': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'Start date (yyyy-MM-dd, '
                                                                        'defaults to 1 year ago).',
                                                         'format': 'date'},
                                           'endDate': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'End date (yyyy-MM-dd, '
                                                                      'defaults to today).',
                                                       'format': 'date'},
                                           'limit': {'location': 'query',
                                                     'required': False,
                                                     'type': 'integer',
                                                     'description': 'Maximum rows to return '
                                                                    '(1–500; default varies per '
                                                                    'endpoint).',
                                                     'minimum': 1,
                                                     'maximum': 500},
                                           'offset': {'location': 'query',
                                                      'required': False,
                                                      'type': 'integer',
                                                      'description': 'Rows to skip before the '
                                                                     'first returned row (default '
                                                                     '0).'},
                                           'interval': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'daily (default), weekly or '
                                                                       'monthly. Weekly (ISO week) '
                                                                       'and monthly bars roll up '
                                                                       'the daily bars: first '
                                                                       'open, highest high, lowest '
                                                                       'low, last close and '
                                                                       'adjusted close, summed '
                                                                       'volume, dated by their '
                                                                       'last session, with '
                                                                       'periodStart and partial '
                                                                       'set.'}},
                            'live': False},
                 'quote': {'name': 'quote',
                           'path': '/stocks/{ticker}/quote',
                           'parameters': {'ticker': {'location': 'path',
                                                     'required': True,
                                                     'type': 'string',
                                                     'description': 'Exact listed ticker (e.g. '
                                                                    'GOOG, GOOGL, BRK-A, or '
                                                                    'BRK-B), or MIC:TICKER for a '
                                                                    'Canadian, Euronext or NSE '
                                                                    'listing (e.g. XTSE:RY, '
                                                                    'XPAR:AIR or XNSE:RELIANCE). A '
                                                                    'missing listing is never '
                                                                    'replaced by its sibling; dot '
                                                                    'class-share spelling such as '
                                                                    'BRK.B is accepted as BRK-B.'}},
                           'live': False},
                 'splits': {'name': 'splits',
                            'path': '/stocks/{ticker}/splits',
                            'parameters': {'ticker': {'location': 'path',
                                                      'required': True,
                                                      'type': 'string',
                                                      'description': 'Listed stock or ETF ticker '
                                                                     '(e.g. NVDA, BRK.B, SCHD), or '
                                                                     'MIC:TICKER for a listing on '
                                                                     'another exchange (e.g. '
                                                                     'XAMS:ASML).'},
                                           'startDate': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'Earliest effective date '
                                                                        '(yyyy-MM-dd).',
                                                         'format': 'date'},
                                           'endDate': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Latest effective date '
                                                                      '(yyyy-MM-dd).',
                                                       'format': 'date'},
                                           'limit': {'location': 'query',
                                                     'required': False,
                                                     'type': 'integer',
                                                     'description': 'Maximum rows to return '
                                                                    '(1–500; default varies per '
                                                                    'endpoint).',
                                                     'minimum': 1,
                                                     'maximum': 500},
                                           'offset': {'location': 'query',
                                                      'required': False,
                                                      'type': 'integer',
                                                      'description': 'Rows to skip before the '
                                                                     'first returned row (default '
                                                                     '0).'}},
                            'live': False},
                 'technicals_atr': {'name': 'technicals_atr',
                                    'path': '/stocks/{ticker}/technicals/atr',
                                    'parameters': {'ticker': {'location': 'path',
                                                              'required': True,
                                                              'type': 'string',
                                                              'description': 'Exact listed ticker '
                                                                             '(e.g. GOOG or '
                                                                             'GOOGL), or '
                                                                             'MIC:TICKER for a '
                                                                             'listing on another '
                                                                             'exchange (e.g. '
                                                                             'XETR:SIE), computed '
                                                                             'in its trading '
                                                                             'currency in major '
                                                                             'units. Each listing '
                                                                             'uses its own bars; '
                                                                             'dot class-share '
                                                                             'spelling such as '
                                                                             'BRK.B is accepted as '
                                                                             'BRK-B.'},
                                                   'startDate': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Start date '
                                                                                '(yyyy-MM-dd, '
                                                                                'defaults to 6 '
                                                                                'months ago).',
                                                                 'format': 'date'},
                                                   'endDate': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'End date '
                                                                              '(yyyy-MM-dd, '
                                                                              'defaults to today).',
                                                               'format': 'date'},
                                                   'period': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Lookback period '
                                                                             '(default 14, minimum '
                                                                             '2).',
                                                              'default': 14,
                                                              'minimum': 2},
                                                   'limit': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Most recent points to '
                                                                            'return (default 60, '
                                                                            'max 500).',
                                                             'minimum': 1,
                                                             'maximum': 500}},
                                    'live': False},
                 'technicals_bollinger_bands': {'name': 'technicals_bollinger_bands',
                                                'path': '/stocks/{ticker}/technicals/bollinger-bands',
                                                'parameters': {'ticker': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'string',
                                                                          'description': 'Exact '
                                                                                         'listed '
                                                                                         'ticker '
                                                                                         '(e.g. '
                                                                                         'GOOG or '
                                                                                         'GOOGL), '
                                                                                         'or '
                                                                                         'MIC:TICKER '
                                                                                         'for a '
                                                                                         'listing '
                                                                                         'on '
                                                                                         'another '
                                                                                         'exchange '
                                                                                         '(e.g. '
                                                                                         'XETR:SIE), '
                                                                                         'computed '
                                                                                         'in its '
                                                                                         'trading '
                                                                                         'currency '
                                                                                         'in major '
                                                                                         'units. '
                                                                                         'Each '
                                                                                         'listing '
                                                                                         'uses its '
                                                                                         'own '
                                                                                         'bars; '
                                                                                         'dot '
                                                                                         'class-share '
                                                                                         'spelling '
                                                                                         'such as '
                                                                                         'BRK.B is '
                                                                                         'accepted '
                                                                                         'as '
                                                                                         'BRK-B.'},
                                                               'startDate': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'string',
                                                                             'description': 'Start '
                                                                                            'date '
                                                                                            '(yyyy-MM-dd, '
                                                                                            'defaults '
                                                                                            'to 6 '
                                                                                            'months '
                                                                                            'ago).',
                                                                             'format': 'date'},
                                                               'endDate': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'string',
                                                                           'description': 'End '
                                                                                          'date '
                                                                                          '(yyyy-MM-dd, '
                                                                                          'defaults '
                                                                                          'to '
                                                                                          'today).',
                                                                           'format': 'date'},
                                                               'period': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'integer',
                                                                          'description': 'Moving-average '
                                                                                         'period '
                                                                                         '(default '
                                                                                         '20, '
                                                                                         'minimum '
                                                                                         '2).',
                                                                          'default': 20,
                                                                          'minimum': 2},
                                                               'stdDev': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'number',
                                                                          'description': 'Standard-deviation '
                                                                                         'multiple '
                                                                                         'for the '
                                                                                         'bands '
                                                                                         '(default '
                                                                                         '2, must '
                                                                                         'be '
                                                                                         'greater '
                                                                                         'than 0).',
                                                                          'default': 2.0},
                                                               'limit': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Most '
                                                                                        'recent '
                                                                                        'points to '
                                                                                        'return '
                                                                                        '(default '
                                                                                        '60, max '
                                                                                        '500).',
                                                                         'minimum': 1,
                                                                         'maximum': 500}},
                                                'live': False},
                 'technicals_obv': {'name': 'technicals_obv',
                                    'path': '/stocks/{ticker}/technicals/obv',
                                    'parameters': {'ticker': {'location': 'path',
                                                              'required': True,
                                                              'type': 'string',
                                                              'description': 'Exact listed ticker '
                                                                             '(e.g. GOOG or '
                                                                             'GOOGL), or '
                                                                             'MIC:TICKER for a '
                                                                             'listing on another '
                                                                             'exchange (e.g. '
                                                                             'XETR:SIE), computed '
                                                                             'in its trading '
                                                                             'currency in major '
                                                                             'units. Each listing '
                                                                             'uses its own bars; '
                                                                             'dot class-share '
                                                                             'spelling such as '
                                                                             'BRK.B is accepted as '
                                                                             'BRK-B.'},
                                                   'startDate': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Start date '
                                                                                '(yyyy-MM-dd, '
                                                                                'defaults to 6 '
                                                                                'months ago).',
                                                                 'format': 'date'},
                                                   'endDate': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'End date '
                                                                              '(yyyy-MM-dd, '
                                                                              'defaults to today).',
                                                               'format': 'date'},
                                                   'limit': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Most recent points to '
                                                                            'return (default 60, '
                                                                            'max 500).',
                                                             'minimum': 1,
                                                             'maximum': 500}},
                                    'live': False},
                 'technicals_stochastic': {'name': 'technicals_stochastic',
                                           'path': '/stocks/{ticker}/technicals/stochastic',
                                           'parameters': {'ticker': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'string',
                                                                     'description': 'Exact listed '
                                                                                    'ticker (e.g. '
                                                                                    'GOOG or '
                                                                                    'GOOGL), or '
                                                                                    'MIC:TICKER '
                                                                                    'for a listing '
                                                                                    'on another '
                                                                                    'exchange '
                                                                                    '(e.g. '
                                                                                    'XETR:SIE), '
                                                                                    'computed in '
                                                                                    'its trading '
                                                                                    'currency in '
                                                                                    'major units. '
                                                                                    'Each listing '
                                                                                    'uses its own '
                                                                                    'bars; dot '
                                                                                    'class-share '
                                                                                    'spelling such '
                                                                                    'as BRK.B is '
                                                                                    'accepted as '
                                                                                    'BRK-B.'},
                                                          'startDate': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': 'Start date '
                                                                                       '(yyyy-MM-dd, '
                                                                                       'defaults '
                                                                                       'to 6 '
                                                                                       'months '
                                                                                       'ago).',
                                                                        'format': 'date'},
                                                          'endDate': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'End date '
                                                                                     '(yyyy-MM-dd, '
                                                                                     'defaults to '
                                                                                     'today).',
                                                                      'format': 'date'},
                                                          'kPeriod': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': '%K lookback '
                                                                                     'period '
                                                                                     '(default 14, '
                                                                                     'minimum 2).',
                                                                      'default': 14,
                                                                      'minimum': 2},
                                                          'dPeriod': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': '%D smoothing '
                                                                                     'period '
                                                                                     '(default 3, '
                                                                                     'minimum 1).',
                                                                      'default': 3,
                                                                      'minimum': 1},
                                                          'limit': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Most recent '
                                                                                   'points to '
                                                                                   'return '
                                                                                   '(default 60, '
                                                                                   'max 500).',
                                                                    'minimum': 1,
                                                                    'maximum': 500}},
                                           'live': False}},
 'ownership': {'security_beneficial_ownership': {'name': 'security_beneficial_ownership',
                                                 'path': '/securities/{ticker}/beneficial-ownership',
                                                 'parameters': {'ticker': {'location': 'path',
                                                                           'required': True,
                                                                           'type': 'string',
                                                                           'description': 'Listed '
                                                                                          'security '
                                                                                          'ticker '
                                                                                          '(e.g. '
                                                                                          'NVDA or '
                                                                                          'BRK-B).'},
                                                                'limit': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'integer',
                                                                          'description': 'Maximum '
                                                                                         'rows to '
                                                                                         'return '
                                                                                         '(1–500; '
                                                                                         'default '
                                                                                         'varies '
                                                                                         'per '
                                                                                         'endpoint).',
                                                                          'minimum': 1,
                                                                          'maximum': 500},
                                                                'offset': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'integer',
                                                                           'description': 'Rows to '
                                                                                          'skip '
                                                                                          'before '
                                                                                          'the '
                                                                                          'first '
                                                                                          'returned '
                                                                                          'row '
                                                                                          '(default '
                                                                                          '0).'}},
                                                 'live': False},
               'security_fund_owners': {'name': 'security_fund_owners',
                                        'path': '/securities/{ticker}/fund-owners',
                                        'parameters': {'ticker': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Listed security '
                                                                                 'ticker (e.g. '
                                                                                 'AAPL or VOO), or '
                                                                                 'MIC:TICKER for a '
                                                                                 'listing on '
                                                                                 'another exchange '
                                                                                 '(e.g. '
                                                                                 'XAMS:ASML).'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum rows to '
                                                                                'return (1–500; '
                                                                                'default varies '
                                                                                'per endpoint).',
                                                                 'minimum': 1,
                                                                 'maximum': 500},
                                                       'offset': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Rows to skip '
                                                                                 'before the first '
                                                                                 'returned row '
                                                                                 '(default 0).'},
                                                       'registrantOrSeries': {'location': 'query',
                                                                              'required': False,
                                                                              'type': 'string',
                                                                              'description': 'Optional '
                                                                                             'case-insensitive '
                                                                                             'substring '
                                                                                             'filter '
                                                                                             'on '
                                                                                             'registrant '
                                                                                             'or '
                                                                                             'fund-series '
                                                                                             'name.'}},
                                        'live': False},
               'security_holder_mix': {'name': 'security_holder_mix',
                                       'path': '/securities/{ticker}/holder-mix',
                                       'parameters': {'ticker': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'Listed security '
                                                                                'ticker (e.g. AAPL '
                                                                                'or VOO).'},
                                                      'dimension': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'How to split '
                                                                                   'the holders: '
                                                                                   'type '
                                                                                   '(default), '
                                                                                   'style, '
                                                                                   'turnover, '
                                                                                   'horizon, aum '
                                                                                   '(13F book '
                                                                                   'size), client '
                                                                                   '(client base), '
                                                                                   'pf (private '
                                                                                   'funds), '
                                                                                   'country (filer '
                                                                                   'location) or '
                                                                                   'fundtype '
                                                                                   '(registered '
                                                                                   'funds by N-CEN '
                                                                                   'fund type).'},
                                                      'periods': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Quarters to '
                                                                                 'return, newest '
                                                                                 'last (default 4, '
                                                                                 'max 12); each is '
                                                                                 'compared with '
                                                                                 'the quarter '
                                                                                 'before.',
                                                                  'default': 4,
                                                                  'maximum': 12}},
                                       'live': False},
               'security_holder_targets': {'name': 'security_holder_targets',
                                           'path': '/securities/{ticker}/holder-targets',
                                           'parameters': {'ticker': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'string',
                                                                     'description': 'Listed '
                                                                                    'security '
                                                                                    'ticker (e.g. '
                                                                                    'NVDA).'},
                                                          'limit': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Maximum rows '
                                                                                   'to return '
                                                                                   '(1–500; '
                                                                                   'default varies '
                                                                                   'per endpoint).',
                                                                    'minimum': 1,
                                                                    'maximum': 500},
                                                          'offset': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Rows to skip '
                                                                                    'before the '
                                                                                    'first '
                                                                                    'returned row '
                                                                                    '(default 0).'},
                                                          'sort': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'peerValue '
                                                                                  '(default) or '
                                                                                  'peerWeight.',
                                                                   'default': 'peerValue'}},
                                           'live': False},
               'security_holders': {'name': 'security_holders',
                                    'path': '/securities/{ticker}/holders',
                                    'parameters': {'ticker': {'location': 'path',
                                                              'required': True,
                                                              'type': 'string',
                                                              'description': 'Listed security '
                                                                             'ticker (e.g. NVDA or '
                                                                             'VOO).'},
                                                   'limit': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Maximum rows to '
                                                                            'return (1–500; '
                                                                            'default varies per '
                                                                            'endpoint).',
                                                             'minimum': 1,
                                                             'maximum': 500},
                                                   'offset': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Rows to skip before '
                                                                             'the first returned '
                                                                             'row (default 0).'},
                                                   'source': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Rows to list: all '
                                                                             '(default), 13f, 13dg '
                                                                             '(13D and 13G), 13d, '
                                                                             '13g, insider, fund '
                                                                             'or nonus. A single '
                                                                             'source lists its '
                                                                             'rows flat, stale '
                                                                             'ones flagged.'},
                                                   'view': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'default (one row per '
                                                                           'holder, others '
                                                                           'nested), all (every '
                                                                           'row flat, stale '
                                                                           'included) or ultimate '
                                                                           '(summed holders '
                                                                           'grouped by ultimate '
                                                                           'parent; takes no '
                                                                           'source or holderTypes '
                                                                           'filter).'},
                                                   'holderTypes': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Comma-separated '
                                                                                  'holder type '
                                                                                  'tokens to keep: '
                                                                                  'adv, era, ia, '
                                                                                  'bank, ins, bd, '
                                                                                  'fund, plan, '
                                                                                  'nonus, hc, unk '
                                                                                  '(insiders and '
                                                                                  'holders without '
                                                                                  'a deciding '
                                                                                  'record read '
                                                                                  'unk).'}},
                                    'live': False},
               'security_institutional_activity': {'name': 'security_institutional_activity',
                                                   'path': '/securities/{ticker}/institutional-activity',
                                                   'parameters': {'ticker': {'location': 'path',
                                                                             'required': True,
                                                                             'type': 'string',
                                                                             'description': 'Listed '
                                                                                            'security '
                                                                                            'ticker '
                                                                                            '(e.g. '
                                                                                            'AAPL '
                                                                                            'or '
                                                                                            'VOO).'},
                                                                  'reportDate': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'string',
                                                                                 'description': '13F '
                                                                                                'report '
                                                                                                'date '
                                                                                                '(yyyy-MM-dd, '
                                                                                                'defaults '
                                                                                                'to '
                                                                                                'the '
                                                                                                'latest '
                                                                                                'available). '
                                                                                                'Must '
                                                                                                'be '
                                                                                                'one '
                                                                                                'of '
                                                                                                'the '
                                                                                                "stock's "
                                                                                                '13F '
                                                                                                'report '
                                                                                                'dates '
                                                                                                '; '
                                                                                                'any '
                                                                                                'other '
                                                                                                'date '
                                                                                                'returns '
                                                                                                '400 '
                                                                                                'listing '
                                                                                                'the '
                                                                                                'available '
                                                                                                'dates.',
                                                                                 'format': 'date'},
                                                                  'limit': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'integer',
                                                                            'description': 'Maximum '
                                                                                           'buyers '
                                                                                           'and '
                                                                                           'sellers '
                                                                                           'to '
                                                                                           'return '
                                                                                           'per '
                                                                                           'side '
                                                                                           '(default '
                                                                                           '10, '
                                                                                           'max '
                                                                                           '500).',
                                                                            'default': 10,
                                                                            'minimum': 1,
                                                                            'maximum': 500}},
                                                   'live': False},
               'security_institutional_holders': {'name': 'security_institutional_holders',
                                                  'path': '/securities/{ticker}/institutional-holders',
                                                  'parameters': {'ticker': {'location': 'path',
                                                                            'required': True,
                                                                            'type': 'string',
                                                                            'description': 'Listed '
                                                                                           'security '
                                                                                           'ticker '
                                                                                           '(e.g. '
                                                                                           'AAPL '
                                                                                           'or '
                                                                                           'VOO).'},
                                                                 'reportDate': {'location': 'query',
                                                                                'required': False,
                                                                                'type': 'string',
                                                                                'description': '13F '
                                                                                               'report '
                                                                                               'date '
                                                                                               '(yyyy-MM-dd, '
                                                                                               'defaults '
                                                                                               'to '
                                                                                               'the '
                                                                                               'latest '
                                                                                               'available). '
                                                                                               'Must '
                                                                                               'be '
                                                                                               'one '
                                                                                               'of '
                                                                                               'the '
                                                                                               "stock's "
                                                                                               '13F '
                                                                                               'report '
                                                                                               'dates '
                                                                                               '; '
                                                                                               'any '
                                                                                               'other '
                                                                                               'date '
                                                                                               'returns '
                                                                                               '400 '
                                                                                               'listing '
                                                                                               'the '
                                                                                               'available '
                                                                                               'dates.',
                                                                                'format': 'date'},
                                                                 'limit': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'integer',
                                                                           'description': 'Maximum '
                                                                                          'rows to '
                                                                                          'return '
                                                                                          '(1–500; '
                                                                                          'default '
                                                                                          'varies '
                                                                                          'per '
                                                                                          'endpoint).',
                                                                           'minimum': 1,
                                                                           'maximum': 500},
                                                                 'offset': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'integer',
                                                                            'description': 'Rows '
                                                                                           'to '
                                                                                           'skip '
                                                                                           'before '
                                                                                           'the '
                                                                                           'first '
                                                                                           'returned '
                                                                                           'row '
                                                                                           '(default '
                                                                                           '0).'},
                                                                 'holderTypes': {'location': 'query',
                                                                                 'required': False,
                                                                                 'type': 'string',
                                                                                 'description': 'Comma-separated '
                                                                                                'holder '
                                                                                                'type '
                                                                                                'tokens '
                                                                                                'to '
                                                                                                'keep: '
                                                                                                'adv, '
                                                                                                'era, '
                                                                                                'ia, '
                                                                                                'bank, '
                                                                                                'ins, '
                                                                                                'bd, '
                                                                                                'fund, '
                                                                                                'plan, '
                                                                                                'nonus, '
                                                                                                'hc, '
                                                                                                'unk '
                                                                                                '(unk '
                                                                                                'also '
                                                                                                'matches '
                                                                                                'a '
                                                                                                'holder '
                                                                                                'not '
                                                                                                'yet '
                                                                                                'classified). '
                                                                                                'Totals '
                                                                                                'and '
                                                                                                'percentages '
                                                                                                'stay '
                                                                                                'over '
                                                                                                'every '
                                                                                                'institution.'},
                                                                 'styles': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'string',
                                                                            'description': 'Comma-separated '
                                                                                           'style '
                                                                                           'band '
                                                                                           'tokens '
                                                                                           'to '
                                                                                           'keep: '
                                                                                           'idx '
                                                                                           '(index-like), '
                                                                                           'sys '
                                                                                           '(systematic-like), '
                                                                                           'conc '
                                                                                           '(concentrated), '
                                                                                           'divact '
                                                                                           '(diversified '
                                                                                           'active), '
                                                                                           'unk '
                                                                                           '(book '
                                                                                           'too '
                                                                                           'small '
                                                                                           'or '
                                                                                           'unvalued '
                                                                                           'to '
                                                                                           'band). '
                                                                                           'Bands '
                                                                                           'come '
                                                                                           'from '
                                                                                           'the '
                                                                                           'newest '
                                                                                           'measured '
                                                                                           'quarter '
                                                                                           'on or '
                                                                                           'before '
                                                                                           'the '
                                                                                           'report '
                                                                                           'date; '
                                                                                           'a '
                                                                                           'holder '
                                                                                           'not '
                                                                                           'measured '
                                                                                           'that '
                                                                                           'quarter '
                                                                                           'matches '
                                                                                           'no '
                                                                                           'style. '
                                                                                           'Totals '
                                                                                           'and '
                                                                                           'percentages '
                                                                                           'stay '
                                                                                           'over '
                                                                                           'every '
                                                                                           'institution.'}},
                                                  'live': False},
               'security_institutional_ownership': {'name': 'security_institutional_ownership',
                                                    'path': '/securities/{ticker}/institutional-ownership',
                                                    'parameters': {'ticker': {'location': 'path',
                                                                              'required': True,
                                                                              'type': 'string',
                                                                              'description': 'Listed '
                                                                                             'security '
                                                                                             'ticker '
                                                                                             '(e.g. '
                                                                                             'AAPL '
                                                                                             'or '
                                                                                             'VOO).'},
                                                                   'periods': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'integer',
                                                                               'description': 'Maximum '
                                                                                              'number '
                                                                                              'of '
                                                                                              'quarterly '
                                                                                              'periods '
                                                                                              'to '
                                                                                              'return '
                                                                                              '(default '
                                                                                              '8, '
                                                                                              'max '
                                                                                              '500).',
                                                                               'default': 8,
                                                                               'maximum': 500}},
                                                    'live': False},
               'security_ownership_signals': {'name': 'security_ownership_signals',
                                              'path': '/securities/{ticker}/ownership-signals',
                                              'parameters': {'ticker': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'string',
                                                                        'description': 'Listed '
                                                                                       'security '
                                                                                       'ticker '
                                                                                       '(e.g. '
                                                                                       'NVDA).'},
                                                             'holders': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Highest-conviction '
                                                                                        'holders '
                                                                                        'to list '
                                                                                        '(default '
                                                                                        '10, max '
                                                                                        '50).',
                                                                         'default': 10,
                                                                         'maximum': 50},
                                                             'peers': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': 'Holder-overlap '
                                                                                      'peers to '
                                                                                      'list '
                                                                                      '(default '
                                                                                      '10, max '
                                                                                      '20).',
                                                                       'default': 10,
                                                                       'maximum': 20}},
                                              'live': False},
               'security_ownership_summary': {'name': 'security_ownership_summary',
                                              'path': '/securities/{ticker}/ownership-summary',
                                              'parameters': {'ticker': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'string',
                                                                        'description': 'Listed '
                                                                                       'security '
                                                                                       'ticker '
                                                                                       '(e.g. NVDA '
                                                                                       'or VOO).'},
                                                             'view': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'default, or '
                                                                                     'ultimate to '
                                                                                     'add the 15 '
                                                                                     'largest '
                                                                                     'ultimate '
                                                                                     'parents.'}},
                                              'live': False},
               'beneficial_ownership': {'name': 'beneficial_ownership',
                                        'path': '/stocks/{ticker}/beneficial-ownership',
                                        'parameters': {'ticker': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Listed security '
                                                                                 'ticker (e.g. '
                                                                                 'NVDA or BRK-B).'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum rows to '
                                                                                'return (1–500; '
                                                                                'default varies '
                                                                                'per endpoint).',
                                                                 'minimum': 1,
                                                                 'maximum': 500},
                                                       'offset': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Rows to skip '
                                                                                 'before the first '
                                                                                 'returned row '
                                                                                 '(default 0).'}},
                                        'live': False},
               'fund_owners': {'name': 'fund_owners',
                               'path': '/stocks/{ticker}/fund-owners',
                               'parameters': {'ticker': {'location': 'path',
                                                         'required': True,
                                                         'type': 'string',
                                                         'description': 'Listed security ticker '
                                                                        '(e.g. AAPL or VOO), or '
                                                                        'MIC:TICKER for a listing '
                                                                        'on another exchange (e.g. '
                                                                        'XAMS:ASML).'},
                                              'limit': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Maximum rows to return '
                                                                       '(1–500; default varies per '
                                                                       'endpoint).',
                                                        'minimum': 1,
                                                        'maximum': 500},
                                              'offset': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Rows to skip before the '
                                                                        'first returned row '
                                                                        '(default 0).'},
                                              'registrantOrSeries': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'string',
                                                                     'description': 'Optional '
                                                                                    'case-insensitive '
                                                                                    'substring '
                                                                                    'filter on '
                                                                                    'registrant or '
                                                                                    'fund-series '
                                                                                    'name.'}},
                               'live': False},
               'holder_mix': {'name': 'holder_mix',
                              'path': '/stocks/{ticker}/holder-mix',
                              'parameters': {'ticker': {'location': 'path',
                                                        'required': True,
                                                        'type': 'string',
                                                        'description': 'Listed security ticker '
                                                                       '(e.g. AAPL or VOO).'},
                                             'dimension': {'location': 'query',
                                                           'required': False,
                                                           'type': 'string',
                                                           'description': 'How to split the '
                                                                          'holders: type '
                                                                          '(default), style, '
                                                                          'turnover, horizon, aum '
                                                                          '(13F book size), client '
                                                                          '(client base), pf '
                                                                          '(private funds), '
                                                                          'country (filer '
                                                                          'location) or fundtype '
                                                                          '(registered funds by '
                                                                          'N-CEN fund type).'},
                                             'periods': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Quarters to return, '
                                                                        'newest last (default 4, '
                                                                        'max 12); each is compared '
                                                                        'with the quarter before.',
                                                         'default': 4,
                                                         'maximum': 12}},
                              'live': False},
               'holder_targets': {'name': 'holder_targets',
                                  'path': '/stocks/{ticker}/holder-targets',
                                  'parameters': {'ticker': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Listed security ticker '
                                                                           '(e.g. NVDA).'},
                                                 'limit': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Maximum rows to return '
                                                                          '(1–500; default varies '
                                                                          'per endpoint).',
                                                           'minimum': 1,
                                                           'maximum': 500},
                                                 'offset': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Rows to skip before '
                                                                           'the first returned row '
                                                                           '(default 0).'},
                                                 'sort': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'peerValue (default) or '
                                                                         'peerWeight.',
                                                          'default': 'peerValue'}},
                                  'live': False},
               'holders': {'name': 'holders',
                           'path': '/stocks/{ticker}/holders',
                           'parameters': {'ticker': {'location': 'path',
                                                     'required': True,
                                                     'type': 'string',
                                                     'description': 'Listed security ticker (e.g. '
                                                                    'NVDA or VOO).'},
                                          'limit': {'location': 'query',
                                                    'required': False,
                                                    'type': 'integer',
                                                    'description': 'Maximum rows to return (1–500; '
                                                                   'default varies per endpoint).',
                                                    'minimum': 1,
                                                    'maximum': 500},
                                          'offset': {'location': 'query',
                                                     'required': False,
                                                     'type': 'integer',
                                                     'description': 'Rows to skip before the first '
                                                                    'returned row (default 0).'},
                                          'source': {'location': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'Rows to list: all (default), '
                                                                    '13f, 13dg (13D and 13G), 13d, '
                                                                    '13g, insider, fund or nonus. '
                                                                    'A single source lists its '
                                                                    'rows flat, stale ones '
                                                                    'flagged.'},
                                          'view': {'location': 'query',
                                                   'required': False,
                                                   'type': 'string',
                                                   'description': 'default (one row per holder, '
                                                                  'others nested), all (every row '
                                                                  'flat, stale included) or '
                                                                  'ultimate (summed holders '
                                                                  'grouped by ultimate parent; '
                                                                  'takes no source or holderTypes '
                                                                  'filter).'},
                                          'holderTypes': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Comma-separated holder '
                                                                         'type tokens to keep: '
                                                                         'adv, era, ia, bank, ins, '
                                                                         'bd, fund, plan, nonus, '
                                                                         'hc, unk (insiders and '
                                                                         'holders without a '
                                                                         'deciding record read '
                                                                         'unk).'}},
                           'live': False},
               'insider_ownership': {'name': 'insider_ownership',
                                     'path': '/stocks/{ticker}/insider-ownership',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Stock ticker symbol '
                                                                              '(e.g. AAPL).'},
                                                    'limit': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Maximum rows to '
                                                                             'return (1–500; '
                                                                             'default varies per '
                                                                             'endpoint).',
                                                              'minimum': 1,
                                                              'maximum': 500},
                                                    'offset': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': 'Rows to skip before '
                                                                              'the first returned '
                                                                              'row (default 0).'}},
                                     'live': False},
               'insider_transactions': {'name': 'insider_transactions',
                                        'path': '/stocks/{ticker}/insider-transactions',
                                        'parameters': {'ticker': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Stock ticker '
                                                                                 'symbol (e.g. '
                                                                                 'AAPL).'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum rows to '
                                                                                'return (1–500; '
                                                                                'default varies '
                                                                                'per endpoint).',
                                                                 'minimum': 1,
                                                                 'maximum': 500},
                                                       'offset': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Rows to skip '
                                                                                 'before the first '
                                                                                 'returned row '
                                                                                 '(default 0).'},
                                                       'startDate': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'string',
                                                                     'description': 'Only include '
                                                                                    'transactions '
                                                                                    'on or after '
                                                                                    'this date '
                                                                                    '(yyyy-MM-dd).',
                                                                     'format': 'date'},
                                                       'endDate': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Only include '
                                                                                  'transactions on '
                                                                                  'or before this '
                                                                                  'date '
                                                                                  '(yyyy-MM-dd).',
                                                                   'format': 'date'},
                                                       'transactionType': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'string',
                                                                           'description': 'Optional '
                                                                                          'transaction '
                                                                                          'type: '
                                                                                          'Buy, '
                                                                                          'Sell, '
                                                                                          'Award, '
                                                                                          'Conversion, '
                                                                                          'Exercise, '
                                                                                          'TaxPayment, '
                                                                                          'Expiration, '
                                                                                          'Gift, '
                                                                                          'Inheritance, '
                                                                                          'Discretionary, '
                                                                                          'or '
                                                                                          'Other. '
                                                                                          'Purchase '
                                                                                          'and '
                                                                                          'Sale '
                                                                                          'are '
                                                                                          'accepted '
                                                                                          'aliases.'},
                                                       'insiderName': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'Only '
                                                                                      'include '
                                                                                      'transactions '
                                                                                      'whose '
                                                                                      'SEC-filed '
                                                                                      'insider '
                                                                                      'name '
                                                                                      'contains '
                                                                                      'every '
                                                                                      'supplied '
                                                                                      'word, '
                                                                                      'case-insensitively.'}},
                                        'live': False},
               'institutional_activity': {'name': 'institutional_activity',
                                          'path': '/stocks/{ticker}/institutional-activity',
                                          'parameters': {'ticker': {'location': 'path',
                                                                    'required': True,
                                                                    'type': 'string',
                                                                    'description': 'Listed '
                                                                                   'security '
                                                                                   'ticker (e.g. '
                                                                                   'AAPL or VOO).'},
                                                         'reportDate': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': '13F report '
                                                                                       'date '
                                                                                       '(yyyy-MM-dd, '
                                                                                       'defaults '
                                                                                       'to the '
                                                                                       'latest '
                                                                                       'available). '
                                                                                       'Must be '
                                                                                       'one of the '
                                                                                       "stock's "
                                                                                       '13F report '
                                                                                       'dates ; '
                                                                                       'any other '
                                                                                       'date '
                                                                                       'returns '
                                                                                       '400 '
                                                                                       'listing '
                                                                                       'the '
                                                                                       'available '
                                                                                       'dates.',
                                                                        'format': 'date'},
                                                         'limit': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Maximum buyers '
                                                                                  'and sellers to '
                                                                                  'return per side '
                                                                                  '(default 10, '
                                                                                  'max 500).',
                                                                   'default': 10,
                                                                   'minimum': 1,
                                                                   'maximum': 500}},
                                          'live': False},
               'institutional_holders': {'name': 'institutional_holders',
                                         'path': '/stocks/{ticker}/institutional-holders',
                                         'parameters': {'ticker': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': 'Listed security '
                                                                                  'ticker (e.g. '
                                                                                  'AAPL or VOO).'},
                                                        'reportDate': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': '13F report '
                                                                                      'date '
                                                                                      '(yyyy-MM-dd, '
                                                                                      'defaults to '
                                                                                      'the latest '
                                                                                      'available). '
                                                                                      'Must be one '
                                                                                      'of the '
                                                                                      "stock's 13F "
                                                                                      'report '
                                                                                      'dates ; any '
                                                                                      'other date '
                                                                                      'returns 400 '
                                                                                      'listing the '
                                                                                      'available '
                                                                                      'dates.',
                                                                       'format': 'date'},
                                                        'limit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Maximum rows to '
                                                                                 'return (1–500; '
                                                                                 'default varies '
                                                                                 'per endpoint).',
                                                                  'minimum': 1,
                                                                  'maximum': 500},
                                                        'offset': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Rows to skip '
                                                                                  'before the '
                                                                                  'first returned '
                                                                                  'row (default '
                                                                                  '0).'},
                                                        'holderTypes': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': 'Comma-separated '
                                                                                       'holder '
                                                                                       'type '
                                                                                       'tokens to '
                                                                                       'keep: adv, '
                                                                                       'era, ia, '
                                                                                       'bank, ins, '
                                                                                       'bd, fund, '
                                                                                       'plan, '
                                                                                       'nonus, hc, '
                                                                                       'unk (unk '
                                                                                       'also '
                                                                                       'matches a '
                                                                                       'holder not '
                                                                                       'yet '
                                                                                       'classified). '
                                                                                       'Totals and '
                                                                                       'percentages '
                                                                                       'stay over '
                                                                                       'every '
                                                                                       'institution.'},
                                                        'styles': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Comma-separated '
                                                                                  'style band '
                                                                                  'tokens to keep: '
                                                                                  'idx '
                                                                                  '(index-like), '
                                                                                  'sys '
                                                                                  '(systematic-like), '
                                                                                  'conc '
                                                                                  '(concentrated), '
                                                                                  'divact '
                                                                                  '(diversified '
                                                                                  'active), unk '
                                                                                  '(book too small '
                                                                                  'or unvalued to '
                                                                                  'band). Bands '
                                                                                  'come from the '
                                                                                  'newest measured '
                                                                                  'quarter on or '
                                                                                  'before the '
                                                                                  'report date; a '
                                                                                  'holder not '
                                                                                  'measured that '
                                                                                  'quarter matches '
                                                                                  'no style. '
                                                                                  'Totals and '
                                                                                  'percentages '
                                                                                  'stay over every '
                                                                                  'institution.'}},
                                         'live': False},
               'institutional_ownership': {'name': 'institutional_ownership',
                                           'path': '/stocks/{ticker}/institutional-ownership',
                                           'parameters': {'ticker': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'string',
                                                                     'description': 'Listed '
                                                                                    'security '
                                                                                    'ticker (e.g. '
                                                                                    'AAPL or '
                                                                                    'VOO).'},
                                                          'periods': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': 'Maximum '
                                                                                     'number of '
                                                                                     'quarterly '
                                                                                     'periods to '
                                                                                     'return '
                                                                                     '(default 8, '
                                                                                     'max 500).',
                                                                      'default': 8,
                                                                      'maximum': 500}},
                                           'live': False},
               'ownership_signals': {'name': 'ownership_signals',
                                     'path': '/stocks/{ticker}/ownership-signals',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Listed security '
                                                                              'ticker (e.g. '
                                                                              'NVDA).'},
                                                    'holders': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Highest-conviction '
                                                                               'holders to list '
                                                                               '(default 10, max '
                                                                               '50).',
                                                                'default': 10,
                                                                'maximum': 50},
                                                    'peers': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Holder-overlap peers '
                                                                             'to list (default 10, '
                                                                             'max 20).',
                                                              'default': 10,
                                                              'maximum': 20}},
                                     'live': False},
               'ownership_summary': {'name': 'ownership_summary',
                                     'path': '/stocks/{ticker}/ownership-summary',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Listed security '
                                                                              'ticker (e.g. NVDA '
                                                                              'or VOO).'},
                                                    'view': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'default, or ultimate '
                                                                            'to add the 15 largest '
                                                                            'ultimate parents.'}},
                                     'live': False},
               'proposed_sales': {'name': 'proposed_sales',
                                  'path': '/stocks/{ticker}/proposed-sales',
                                  'parameters': {'ticker': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Stock ticker symbol '
                                                                           '(e.g. AAPL).'},
                                                 'limit': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Maximum rows to return '
                                                                          '(1–500; default varies '
                                                                          'per endpoint).',
                                                           'minimum': 1,
                                                           'maximum': 500},
                                                 'offset': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Rows to skip before '
                                                                           'the first returned row '
                                                                           '(default 0).'},
                                                 'startDate': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Only include '
                                                                              'notices filed on or '
                                                                              'after this date '
                                                                              '(yyyy-MM-dd).',
                                                               'format': 'date'},
                                                 'endDate': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Only include notices '
                                                                            'filed on or before '
                                                                            'this date '
                                                                            '(yyyy-MM-dd).',
                                                             'format': 'date'}},
                                  'live': False},
               'shareholder_votes': {'name': 'shareholder_votes',
                                     'path': '/stocks/{ticker}/shareholder-votes',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Company ticker '
                                                                              'symbol (e.g. PG).'},
                                                    'limit': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Maximum meetings to '
                                                                             'return (default 1, '
                                                                             'max 10; zero or '
                                                                             'negative values are '
                                                                             'rejected, values '
                                                                             'above the maximum '
                                                                             'are clamped).',
                                                              'minimum': 1,
                                                              'maximum': 10}},
                                     'live': False},
               'supply_chain': {'name': 'supply_chain',
                                'path': '/stocks/{ticker}/supply-chain',
                                'parameters': {'ticker': {'location': 'path',
                                                          'required': True,
                                                          'type': 'string',
                                                          'description': 'Stock ticker (e.g. THO), '
                                                                         'or MIC:TICKER (e.g. '
                                                                         'XPAR:SU) for a listing '
                                                                         'outside the US.'},
                                               'side': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'Only one side: customers, '
                                                                       'suppliers, competitors or '
                                                                       'partners (default: all '
                                                                       'four).'},
                                               'quantifiedOnly': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'boolean',
                                                                  'description': 'Only companies '
                                                                                 'with a stated '
                                                                                 'share (default '
                                                                                 'false).',
                                                                  'default': False},
                                               'lens': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'Order within each side: '
                                                                       'stated (largest stated '
                                                                       'share first, the default), '
                                                                       'dependsOn (largest share '
                                                                       "of this company's revenue "
                                                                       'first) or dependents '
                                                                       '(largest share of the '
                                                                       "other company's own "
                                                                       'revenue first).',
                                                        'default': 'stated'},
                                               'limit': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Maximum companies per '
                                                                        'side (default 50, max '
                                                                        '500); in the stated order '
                                                                        'a company and the parts '
                                                                        'listed under it are kept '
                                                                        'together.',
                                                         'default': 50,
                                                         'minimum': 1,
                                                         'maximum': 500}},
                                'live': False},
               'supply_chain_overlap': {'name': 'supply_chain_overlap',
                                        'path': '/stocks/{ticker}/supply-chain/overlap',
                                        'parameters': {'ticker': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Stock ticker '
                                                                                 '(e.g. NVDA), or '
                                                                                 'MIC:TICKER (e.g. '
                                                                                 'XPAR:SU) for a '
                                                                                 'listing outside '
                                                                                 'the US.'},
                                                       'vs': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': "One competitor's "
                                                                             'ticker, as the '
                                                                             'competitors list '
                                                                             'shows it (e.g. '
                                                                             'AMD).'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum companies '
                                                                                'per list (default '
                                                                                '50, max 500).',
                                                                 'default': 50,
                                                                 'minimum': 1,
                                                                 'maximum': 500}},
                                        'live': False}},
 'positioning': {'security_fails_to_deliver': {'name': 'security_fails_to_deliver',
                                               'path': '/securities/{ticker}/fails-to-deliver',
                                               'parameters': {'ticker': {'location': 'path',
                                                                         'required': True,
                                                                         'type': 'string',
                                                                         'description': 'Exact '
                                                                                        'stock or '
                                                                                        'ETF '
                                                                                        'ticker '
                                                                                        'symbol '
                                                                                        '(e.g. '
                                                                                        'AAPL or '
                                                                                        'SPY).'},
                                                              'startDate': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'string',
                                                                            'description': 'Start '
                                                                                           'settlement '
                                                                                           'date '
                                                                                           '(yyyy-MM-dd, '
                                                                                           'defaults '
                                                                                           'to 3 '
                                                                                           'months '
                                                                                           'ago).',
                                                                            'format': 'date'},
                                                              'endDate': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': 'End '
                                                                                         'settlement '
                                                                                         'date '
                                                                                         '(yyyy-MM-dd, '
                                                                                         'defaults '
                                                                                         'to '
                                                                                         'today).',
                                                                          'format': 'date'},
                                                              'limit': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': 'Maximum '
                                                                                       'rows to '
                                                                                       'return '
                                                                                       '(1–500; '
                                                                                       'default '
                                                                                       'varies per '
                                                                                       'endpoint).',
                                                                        'minimum': 1,
                                                                        'maximum': 500},
                                                              'offset': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': 'Rows to '
                                                                                        'skip '
                                                                                        'before '
                                                                                        'the first '
                                                                                        'returned '
                                                                                        'row '
                                                                                        '(default '
                                                                                        '0).'}},
                                               'live': False},
                 'security_off_exchange_volume': {'name': 'security_off_exchange_volume',
                                                  'path': '/securities/{ticker}/off-exchange-volume',
                                                  'parameters': {'ticker': {'location': 'path',
                                                                            'required': True,
                                                                            'type': 'string',
                                                                            'description': 'Listed '
                                                                                           'security '
                                                                                           'ticker '
                                                                                           '(e.g. '
                                                                                           'AAPL '
                                                                                           'or '
                                                                                           'VOO). '
                                                                                           'Class '
                                                                                           'shares '
                                                                                           'use a '
                                                                                           'dash '
                                                                                           '(BRK-B); '
                                                                                           'the '
                                                                                           'dot '
                                                                                           'form '
                                                                                           '(BRK.B) '
                                                                                           'is '
                                                                                           'also '
                                                                                           'accepted.'},
                                                                 'startDate': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'string',
                                                                               'description': 'Start '
                                                                                              'week '
                                                                                              '(yyyy-MM-dd, '
                                                                                              'defaults '
                                                                                              'to '
                                                                                              '6 '
                                                                                              'months '
                                                                                              'ago).',
                                                                               'format': 'date'},
                                                                 'endDate': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'string',
                                                                             'description': 'End '
                                                                                            'week '
                                                                                            '(yyyy-MM-dd, '
                                                                                            'defaults '
                                                                                            'to '
                                                                                            'today).',
                                                                             'format': 'date'},
                                                                 'limit': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'integer',
                                                                           'description': 'Maximum '
                                                                                          'rows to '
                                                                                          'return '
                                                                                          '(1–500; '
                                                                                          'default '
                                                                                          'varies '
                                                                                          'per '
                                                                                          'endpoint).',
                                                                           'minimum': 1,
                                                                           'maximum': 500},
                                                                 'offset': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'integer',
                                                                            'description': 'Rows '
                                                                                           'to '
                                                                                           'skip '
                                                                                           'before '
                                                                                           'the '
                                                                                           'first '
                                                                                           'returned '
                                                                                           'row '
                                                                                           '(default '
                                                                                           '0).'}},
                                                  'live': False},
                 'security_short_interest': {'name': 'security_short_interest',
                                             'path': '/securities/{ticker}/short-interest',
                                             'parameters': {'ticker': {'location': 'path',
                                                                       'required': True,
                                                                       'type': 'string',
                                                                       'description': 'Listed '
                                                                                      'security '
                                                                                      'ticker '
                                                                                      '(e.g. AAPL '
                                                                                      'or VOO). '
                                                                                      'Class '
                                                                                      'shares use '
                                                                                      'a dash '
                                                                                      '(BRK-B); '
                                                                                      'the dot '
                                                                                      'form '
                                                                                      '(BRK.B) is '
                                                                                      'also '
                                                                                      'accepted.'},
                                                            'startDate': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'string',
                                                                          'description': 'Start '
                                                                                         'settlement '
                                                                                         'date '
                                                                                         '(yyyy-MM-dd, '
                                                                                         'defaults '
                                                                                         'to 1 '
                                                                                         'year '
                                                                                         'ago).',
                                                                          'format': 'date'},
                                                            'endDate': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': 'End '
                                                                                       'settlement '
                                                                                       'date '
                                                                                       '(yyyy-MM-dd, '
                                                                                       'defaults '
                                                                                       'to today).',
                                                                        'format': 'date'},
                                                            'limit': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': 'Maximum rows '
                                                                                     'to return '
                                                                                     '(1–500; '
                                                                                     'default '
                                                                                     'varies per '
                                                                                     'endpoint).',
                                                                      'minimum': 1,
                                                                      'maximum': 500},
                                                            'offset': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': 'Rows to '
                                                                                      'skip before '
                                                                                      'the first '
                                                                                      'returned '
                                                                                      'row '
                                                                                      '(default '
                                                                                      '0).'}},
                                             'live': False},
                 'security_short_volume': {'name': 'security_short_volume',
                                           'path': '/securities/{ticker}/short-volume',
                                           'parameters': {'ticker': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'string',
                                                                     'description': 'Listed '
                                                                                    'security '
                                                                                    'ticker (e.g. '
                                                                                    'AAPL or VOO). '
                                                                                    'Class shares '
                                                                                    'use a dash '
                                                                                    '(BRK-B); the '
                                                                                    'dot form '
                                                                                    '(BRK.B) is '
                                                                                    'also '
                                                                                    'accepted.'},
                                                          'startDate': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'string',
                                                                        'description': 'Start date '
                                                                                       '(yyyy-MM-dd, '
                                                                                       'defaults '
                                                                                       'to 3 '
                                                                                       'months '
                                                                                       'ago).',
                                                                        'format': 'date'},
                                                          'endDate': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'End date '
                                                                                     '(yyyy-MM-dd, '
                                                                                     'defaults to '
                                                                                     'today).',
                                                                      'format': 'date'},
                                                          'limit': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Maximum rows '
                                                                                   'to return '
                                                                                   '(1–500; '
                                                                                   'default varies '
                                                                                   'per endpoint).',
                                                                    'minimum': 1,
                                                                    'maximum': 500},
                                                          'offset': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Rows to skip '
                                                                                    'before the '
                                                                                    'first '
                                                                                    'returned row '
                                                                                    '(default '
                                                                                    '0).'}},
                                           'live': False},
                 'short_interest_snapshot': {'name': 'short_interest_snapshot',
                                             'path': '/short-interest/snapshot',
                                             'parameters': {'minDaysToCover': {'location': 'query',
                                                                               'required': False,
                                                                               'type': 'number',
                                                                               'description': 'Minimum '
                                                                                              'days '
                                                                                              'to '
                                                                                              'cover '
                                                                                              'filter '
                                                                                              '(default '
                                                                                              '0 = '
                                                                                              'no '
                                                                                              'filter).',
                                                                               'default': 0.0},
                                                            'minAverageDailyVolume': {'location': 'query',
                                                                                      'required': False,
                                                                                      'type': 'integer',
                                                                                      'description': 'Minimum '
                                                                                                     'average '
                                                                                                     'daily '
                                                                                                     'share '
                                                                                                     'volume '
                                                                                                     '; '
                                                                                                     'set '
                                                                                                     'a '
                                                                                                     'floor '
                                                                                                     '(e.g. '
                                                                                                     '100000) '
                                                                                                     'to '
                                                                                                     'drop '
                                                                                                     'illiquid '
                                                                                                     'names '
                                                                                                     'whose '
                                                                                                     'days-to-cover '
                                                                                                     'is '
                                                                                                     'inflated '
                                                                                                     'by '
                                                                                                     'a '
                                                                                                     'tiny '
                                                                                                     'volume '
                                                                                                     'denominator '
                                                                                                     '(default '
                                                                                                     '0 '
                                                                                                     '= '
                                                                                                     'no '
                                                                                                     'floor).',
                                                                                      'default': 0},
                                                            'minAvgDailyVolume': {'location': 'query',
                                                                                  'required': False,
                                                                                  'type': 'integer',
                                                                                  'description': 'Alias '
                                                                                                 'for '
                                                                                                 'minAverageDailyVolume '
                                                                                                 'matching '
                                                                                                 'the '
                                                                                                 'MCP '
                                                                                                 "tool's "
                                                                                                 'parameter '
                                                                                                 'name; '
                                                                                                 'minAverageDailyVolume '
                                                                                                 'wins '
                                                                                                 'when '
                                                                                                 'both '
                                                                                                 'are '
                                                                                                 'set.',
                                                                                  'default': 0},
                                                            'sortBy': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'Sort key: '
                                                                                      'daysToCover '
                                                                                      '(default; '
                                                                                      'FINRA-capped '
                                                                                      '999.99 '
                                                                                      'sentinel '
                                                                                      'rows ranked '
                                                                                      'last), '
                                                                                      'shortPosition, '
                                                                                      'or change '
                                                                                      '(largest '
                                                                                      'increase in '
                                                                                      'short '
                                                                                      'position '
                                                                                      'first).'},
                                                            'limit': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': 'Maximum rows '
                                                                                     'to return '
                                                                                     '(1–500; '
                                                                                     'default '
                                                                                     'varies per '
                                                                                     'endpoint).',
                                                                      'minimum': 1,
                                                                      'maximum': 500},
                                                            'offset': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': 'Rows to '
                                                                                      'skip before '
                                                                                      'the first '
                                                                                      'returned '
                                                                                      'row '
                                                                                      '(default '
                                                                                      '0).'}},
                                             'live': False},
                 'short_squeeze_scores': {'name': 'short_squeeze_scores',
                                          'path': '/short-squeeze-scores',
                                          'parameters': {'minMarketCap': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'number',
                                                                          'description': 'Minimum '
                                                                                         'market '
                                                                                         'capitalization '
                                                                                         'in US '
                                                                                         'dollars '
                                                                                         '(default '
                                                                                         '0 = no '
                                                                                         'floor). '
                                                                                         'Stocks '
                                                                                         'with an '
                                                                                         'unknown '
                                                                                         'market '
                                                                                         'cap are '
                                                                                         'excluded '
                                                                                         'when '
                                                                                         'set.',
                                                                          'default': 0.0},
                                                         'minDollarVolume': {'location': 'query',
                                                                             'required': False,
                                                                             'type': 'number',
                                                                             'description': 'Minimum '
                                                                                            'average '
                                                                                            'daily '
                                                                                            'dollar '
                                                                                            'volume '
                                                                                            'in US '
                                                                                            'dollars, '
                                                                                            'approximated '
                                                                                            'as '
                                                                                            'the '
                                                                                            'FINRA '
                                                                                            'average '
                                                                                            'daily '
                                                                                            'share '
                                                                                            'volume '
                                                                                            'times '
                                                                                            'the '
                                                                                            'market-cap-implied '
                                                                                            'share '
                                                                                            'price '
                                                                                            '(default '
                                                                                            '0 = '
                                                                                            'no '
                                                                                            'floor). '
                                                                                            'Stocks '
                                                                                            'with '
                                                                                            'unknown '
                                                                                            'volume '
                                                                                            'or '
                                                                                            'market '
                                                                                            'cap '
                                                                                            'are '
                                                                                            'excluded '
                                                                                            'when '
                                                                                            'set.',
                                                                             'default': 0.0},
                                                         'ticker': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'Optional stock '
                                                                                   'ticker (e.g. '
                                                                                   'GME): returns '
                                                                                   'that one '
                                                                                   "stock's score "
                                                                                   'row plus its '
                                                                                   'rank within '
                                                                                   'the scored '
                                                                                   'universe '
                                                                                   'instead of the '
                                                                                   'board; 404 '
                                                                                   'when the stock '
                                                                                   'is not in the '
                                                                                   'scored '
                                                                                   'universe. The '
                                                                                   'liquidity '
                                                                                   'floors do not '
                                                                                   'apply to a '
                                                                                   'single-ticker '
                                                                                   'lookup.'},
                                                         'limit': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Maximum rows to '
                                                                                  'return (1–500; '
                                                                                  'default varies '
                                                                                  'per endpoint).',
                                                                   'minimum': 1,
                                                                   'maximum': 500},
                                                         'offset': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Rows to skip '
                                                                                   'before the '
                                                                                   'first returned '
                                                                                   'row (default '
                                                                                   '0).'}},
                                          'live': False},
                 'short_volume_largest': {'name': 'short_volume_largest',
                                          'path': '/short-volume/largest',
                                          'parameters': {'date': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'Trading day '
                                                                                 '(yyyy-MM-dd, '
                                                                                 'defaults to the '
                                                                                 'latest available '
                                                                                 'day).',
                                                                  'format': 'date'},
                                                         'minShortVolume': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'integer',
                                                                            'description': 'Minimum '
                                                                                           'short '
                                                                                           'volume '
                                                                                           'filter '
                                                                                           '(default '
                                                                                           '0 = no '
                                                                                           'filter).',
                                                                            'default': 0},
                                                         'sortBy': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'Sort key: '
                                                                                   'shortVolume '
                                                                                   '(default) or '
                                                                                   'shortPercent ; '
                                                                                   'with '
                                                                                   'shortPercent '
                                                                                   'set a '
                                                                                   'minTotalVolume '
                                                                                   'floor, '
                                                                                   'otherwise '
                                                                                   'illiquid names '
                                                                                   'dominate.'},
                                                         'minTotalVolume': {'location': 'query',
                                                                            'required': False,
                                                                            'type': 'integer',
                                                                            'description': 'Minimum '
                                                                                           'total '
                                                                                           'FINRA-reported '
                                                                                           'volume '
                                                                                           'filter, '
                                                                                           'in '
                                                                                           'shares '
                                                                                           '(default '
                                                                                           '0 = no '
                                                                                           'floor).',
                                                                            'default': 0},
                                                         'limit': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Maximum rows to '
                                                                                  'return (1–500; '
                                                                                  'default varies '
                                                                                  'per endpoint).',
                                                                   'minimum': 1,
                                                                   'maximum': 500},
                                                         'offset': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Rows to skip '
                                                                                   'before the '
                                                                                   'first returned '
                                                                                   'row (default '
                                                                                   '0).'}},
                                          'live': False},
                 'fails_to_deliver': {'name': 'fails_to_deliver',
                                      'path': '/stocks/{ticker}/fails-to-deliver',
                                      'parameters': {'ticker': {'location': 'path',
                                                                'required': True,
                                                                'type': 'string',
                                                                'description': 'Exact stock or ETF '
                                                                               'ticker symbol '
                                                                               '(e.g. AAPL or '
                                                                               'SPY).'},
                                                     'startDate': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Start '
                                                                                  'settlement date '
                                                                                  '(yyyy-MM-dd, '
                                                                                  'defaults to 3 '
                                                                                  'months ago).',
                                                                   'format': 'date'},
                                                     'endDate': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'End settlement '
                                                                                'date (yyyy-MM-dd, '
                                                                                'defaults to '
                                                                                'today).',
                                                                 'format': 'date'},
                                                     'limit': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': 'Maximum rows to '
                                                                              'return (1–500; '
                                                                              'default varies per '
                                                                              'endpoint).',
                                                               'minimum': 1,
                                                               'maximum': 500},
                                                     'offset': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': 'Rows to skip '
                                                                               'before the first '
                                                                               'returned row '
                                                                               '(default 0).'}},
                                      'live': False},
                 'off_exchange_volume': {'name': 'off_exchange_volume',
                                         'path': '/stocks/{ticker}/off-exchange-volume',
                                         'parameters': {'ticker': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': 'Listed security '
                                                                                  'ticker (e.g. '
                                                                                  'AAPL or VOO). '
                                                                                  'Class shares '
                                                                                  'use a dash '
                                                                                  '(BRK-B); the '
                                                                                  'dot form '
                                                                                  '(BRK.B) is also '
                                                                                  'accepted.'},
                                                        'startDate': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'Start week '
                                                                                     '(yyyy-MM-dd, '
                                                                                     'defaults to '
                                                                                     '6 months '
                                                                                     'ago).',
                                                                      'format': 'date'},
                                                        'endDate': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'End week '
                                                                                   '(yyyy-MM-dd, '
                                                                                   'defaults to '
                                                                                   'today).',
                                                                    'format': 'date'},
                                                        'limit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Maximum rows to '
                                                                                 'return (1–500; '
                                                                                 'default varies '
                                                                                 'per endpoint).',
                                                                  'minimum': 1,
                                                                  'maximum': 500},
                                                        'offset': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Rows to skip '
                                                                                  'before the '
                                                                                  'first returned '
                                                                                  'row (default '
                                                                                  '0).'}},
                                         'live': False},
                 'short_interest': {'name': 'short_interest',
                                    'path': '/stocks/{ticker}/short-interest',
                                    'parameters': {'ticker': {'location': 'path',
                                                              'required': True,
                                                              'type': 'string',
                                                              'description': 'Listed security '
                                                                             'ticker (e.g. AAPL or '
                                                                             'VOO). Class shares '
                                                                             'use a dash (BRK-B); '
                                                                             'the dot form (BRK.B) '
                                                                             'is also accepted.'},
                                                   'startDate': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Start settlement '
                                                                                'date (yyyy-MM-dd, '
                                                                                'defaults to 1 '
                                                                                'year ago).',
                                                                 'format': 'date'},
                                                   'endDate': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'End settlement date '
                                                                              '(yyyy-MM-dd, '
                                                                              'defaults to today).',
                                                               'format': 'date'},
                                                   'limit': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Maximum rows to '
                                                                            'return (1–500; '
                                                                            'default varies per '
                                                                            'endpoint).',
                                                             'minimum': 1,
                                                             'maximum': 500},
                                                   'offset': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Rows to skip before '
                                                                             'the first returned '
                                                                             'row (default 0).'}},
                                    'live': False},
                 'short_interest_forecast': {'name': 'short_interest_forecast',
                                             'path': '/stocks/{ticker}/short-interest/forecast',
                                             'parameters': {'ticker': {'location': 'path',
                                                                       'required': True,
                                                                       'type': 'string',
                                                                       'description': 'Stock '
                                                                                      'ticker '
                                                                                      'symbol '
                                                                                      '(e.g. '
                                                                                      'AAPL). '
                                                                                      'Class '
                                                                                      'shares use '
                                                                                      'a dash '
                                                                                      '(BRK-B); '
                                                                                      'the dot '
                                                                                      'form '
                                                                                      '(BRK.B) is '
                                                                                      'also '
                                                                                      'accepted.'}},
                                             'live': False},
                 'short_volume': {'name': 'short_volume',
                                  'path': '/stocks/{ticker}/short-volume',
                                  'parameters': {'ticker': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Listed security ticker '
                                                                           '(e.g. AAPL or VOO). '
                                                                           'Class shares use a '
                                                                           'dash (BRK-B); the dot '
                                                                           'form (BRK.B) is also '
                                                                           'accepted.'},
                                                 'startDate': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Start date '
                                                                              '(yyyy-MM-dd, '
                                                                              'defaults to 3 '
                                                                              'months ago).',
                                                               'format': 'date'},
                                                 'endDate': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'End date (yyyy-MM-dd, '
                                                                            'defaults to today).',
                                                             'format': 'date'},
                                                 'limit': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Maximum rows to return '
                                                                          '(1–500; default varies '
                                                                          'per endpoint).',
                                                           'minimum': 1,
                                                           'maximum': 500},
                                                 'offset': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Rows to skip before '
                                                                           'the first returned row '
                                                                           '(default 0).'}},
                                  'live': False}},
 'options': {'security_chain': {'name': 'security_chain',
                                'path': '/securities/{ticker}/options/chain',
                                'parameters': {'ticker': {'location': 'path',
                                                          'required': True,
                                                          'type': 'string',
                                                          'description': 'Exact listed underlying '
                                                                         '(e.g. GOOG, GOOGL, '
                                                                         'BRK-A, or BRK-B), or '
                                                                         'MIC:TICKER for a TSX or '
                                                                         'TSXV listing (e.g. '
                                                                         'XTSE:RY). A listing '
                                                                         'never falls through to '
                                                                         'its sibling; dot '
                                                                         'class-share spelling '
                                                                         'such as BRK.B is '
                                                                         'accepted as BRK-B.'},
                                               'expiration': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Expiration date in '
                                                                             'YYYY-MM-DD format '
                                                                             '(default: nearest '
                                                                             'upcoming).',
                                                              'format': 'date'},
                                               'minStrike': {'location': 'query',
                                                             'required': False,
                                                             'type': 'number',
                                                             'description': 'Only include strikes '
                                                                            'at or above this '
                                                                            'price.'},
                                               'maxStrike': {'location': 'query',
                                                             'required': False,
                                                             'type': 'number',
                                                             'description': 'Only include strikes '
                                                                            'at or below this '
                                                                            'price.'},
                                               'type': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'Contract type filter: call '
                                                                       'or put (default: both).'},
                                               'limit': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Maximum contracts to '
                                                                        'return, taken nearest the '
                                                                        'money (default: 250, max: '
                                                                        '500).',
                                                         'default': 250,
                                                         'minimum': 1,
                                                         'maximum': 500}},
                                'live': False},
             'security_contract': {'name': 'security_contract',
                                   'path': '/securities/{ticker}/options/contract',
                                   'parameters': {'ticker': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'Exact listed '
                                                                            'underlying (e.g. '
                                                                            'GOOG, GOOGL, BRK-A, '
                                                                            'or BRK-B), or '
                                                                            'MIC:TICKER for a TSX '
                                                                            'or TSXV listing (e.g. '
                                                                            'XTSE:RY). A listing '
                                                                            'never falls through '
                                                                            'to its sibling; dot '
                                                                            'class-share spelling '
                                                                            'such as BRK.B is '
                                                                            'accepted as BRK-B.'},
                                                  'symbol': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'OCC option symbol '
                                                                            '(e.g. '
                                                                            'O:AAPL260724C00110000).'}},
                                   'live': False},
             'security_contract_bars': {'name': 'security_contract_bars',
                                        'path': '/securities/{ticker}/options/contract/bars',
                                        'parameters': {'ticker': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Exact listed '
                                                                                 'underlying (e.g. '
                                                                                 'GOOG, GOOGL, '
                                                                                 'BRK-A, or '
                                                                                 'BRK-B), or '
                                                                                 'XNSE:SYMBOL for '
                                                                                 'an NSE share or '
                                                                                 'index (e.g. '
                                                                                 'XNSE:RELIANCE, '
                                                                                 'XNSE:NIFTY). A '
                                                                                 'listing never '
                                                                                 'falls through to '
                                                                                 'its sibling; dot '
                                                                                 'class-share '
                                                                                 'spelling such as '
                                                                                 'BRK.B is '
                                                                                 'accepted as '
                                                                                 'BRK-B.'},
                                                       'symbol': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'OCC option '
                                                                                 'symbol (e.g. '
                                                                                 'O:AAPL270617C00350000). '
                                                                                 'An NSE contract '
                                                                                 "is O:, NSE's "
                                                                                 'symbol, the '
                                                                                 'expiry as '
                                                                                 'yyMMdd, C or P, '
                                                                                 'then the strike '
                                                                                 'times 1000 in at '
                                                                                 'least eight '
                                                                                 'digits (e.g. '
                                                                                 'O:NIFTY261117P25100000); '
                                                                                 'percent-encode '
                                                                                 'an ampersand in '
                                                                                 'it (M&M is '
                                                                                 'M%26M).'},
                                                       'timeframe': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'string',
                                                                     'description': 'Bar size: '
                                                                                    'day, hour or '
                                                                                    'minute '
                                                                                    '(default: '
                                                                                    'day).'},
                                                       'startDate': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'string',
                                                                     'description': 'First date, '
                                                                                    'YYYY-MM-DD '
                                                                                    '(default '
                                                                                    'depends on '
                                                                                    'timeframe).',
                                                                     'format': 'date'},
                                                       'endDate': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'Last date, '
                                                                                  'YYYY-MM-DD '
                                                                                  '(default: '
                                                                                  'today).',
                                                                   'format': 'date'},
                                                       'limit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum bars to '
                                                                                'return, newest '
                                                                                'first (default: '
                                                                                '250, max: 500).',
                                                                 'default': 250,
                                                                 'minimum': 1,
                                                                 'maximum': 500}},
                                        'live': False},
             'security_contract_trades': {'name': 'security_contract_trades',
                                          'path': '/securities/{ticker}/options/contract/trades',
                                          'parameters': {'ticker': {'location': 'path',
                                                                    'required': True,
                                                                    'type': 'string',
                                                                    'description': 'Exact listed '
                                                                                   'underlying '
                                                                                   '(e.g. GOOG, '
                                                                                   'GOOGL, BRK-A, '
                                                                                   'or BRK-B). A '
                                                                                   'listing never '
                                                                                   'falls through '
                                                                                   'to its '
                                                                                   'sibling; dot '
                                                                                   'class-share '
                                                                                   'spelling such '
                                                                                   'as BRK.B is '
                                                                                   'accepted as '
                                                                                   'BRK-B.'},
                                                         'symbol': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'string',
                                                                    'description': 'OCC option '
                                                                                   'symbol (e.g. '
                                                                                   'O:AAPL270617C00350000).'},
                                                         'startDate': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'First date, '
                                                                                      'YYYY-MM-DD '
                                                                                      '(default: 4 '
                                                                                      'days before '
                                                                                      'end).',
                                                                       'format': 'date'},
                                                         'endDate': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'string',
                                                                     'description': 'Last date, '
                                                                                    'YYYY-MM-DD '
                                                                                    '(default: '
                                                                                    'today).',
                                                                     'format': 'date'},
                                                         'endTime': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'string',
                                                                     'description': 'Last time to '
                                                                                    'include, RFC '
                                                                                    '3339; '
                                                                                    'replaces '
                                                                                    'endDate. To '
                                                                                    'continue a '
                                                                                    'truncated '
                                                                                    'read, pass '
                                                                                    'the oldest '
                                                                                    "row's time, "
                                                                                    'which can '
                                                                                    'come back '
                                                                                    'again.',
                                                                     'format': 'timestamp'},
                                                         'limit': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Maximum trades '
                                                                                  'to return, '
                                                                                  'newest first '
                                                                                  '(default: 250, '
                                                                                  'max: 500).',
                                                                   'default': 250,
                                                                   'minimum': 1,
                                                                   'maximum': 500}},
                                          'live': False},
             'security_expirations': {'name': 'security_expirations',
                                      'path': '/securities/{ticker}/options/expirations',
                                      'parameters': {'ticker': {'location': 'path',
                                                                'required': True,
                                                                'type': 'string',
                                                                'description': 'Exact listed '
                                                                               'underlying (e.g. '
                                                                               'GOOG, GOOGL, '
                                                                               'BRK-A, or BRK-B), '
                                                                               'or MIC:TICKER for '
                                                                               'a TSX or TSXV '
                                                                               'listing (e.g. '
                                                                               'XTSE:RY). A '
                                                                               'listing never '
                                                                               'falls through to '
                                                                               'its sibling; dot '
                                                                               'class-share '
                                                                               'spelling such as '
                                                                               'BRK.B is accepted '
                                                                               'as BRK-B.'},
                                                     'expired': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'boolean',
                                                                 'description': 'List past '
                                                                                'expirations '
                                                                                'instead of '
                                                                                'upcoming ones (US '
                                                                                'listings only).',
                                                                 'default': False},
                                                     'startDate': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': 'With '
                                                                                  'expired=true: '
                                                                                  'first '
                                                                                  'expiration '
                                                                                  'date, '
                                                                                  'YYYY-MM-DD '
                                                                                  '(default: 90 '
                                                                                  'days before '
                                                                                  'end).',
                                                                   'format': 'date'},
                                                     'endDate': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'With '
                                                                                'expired=true: '
                                                                                'last expiration '
                                                                                'date, YYYY-MM-DD '
                                                                                '(default: '
                                                                                'yesterday).',
                                                                 'format': 'date'}},
                                      'live': False},
             'security_session': {'name': 'security_session',
                                  'path': '/securities/{ticker}/options/session',
                                  'parameters': {'ticker': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Exact listed '
                                                                           'underlying (e.g. GOOG, '
                                                                           'GOOGL, BRK-A, or '
                                                                           'BRK-B). A listing '
                                                                           'never falls through to '
                                                                           'its sibling; dot '
                                                                           'class-share spelling '
                                                                           'such as BRK.B is '
                                                                           'accepted as BRK-B.'},
                                                 'date': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'The session, YYYY-MM-DD.',
                                                          'format': 'date'},
                                                 'expiration': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'The expiration, '
                                                                               'YYYY-MM-DD.',
                                                                'format': 'date'},
                                                 'minStrike': {'location': 'query',
                                                               'required': False,
                                                               'type': 'number',
                                                               'description': 'Only include '
                                                                              'strikes at or above '
                                                                              'this price.'},
                                                 'maxStrike': {'location': 'query',
                                                               'required': False,
                                                               'type': 'number',
                                                               'description': 'Only include '
                                                                              'strikes at or below '
                                                                              'this price.'},
                                                 'type': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Contract type filter: '
                                                                         'call or put (default: '
                                                                         'both).'},
                                                 'limit': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Maximum contracts to '
                                                                          'return, taken nearest '
                                                                          "the session's stock "
                                                                          'close (default: 250, '
                                                                          'max: 500).',
                                                           'default': 250,
                                                           'minimum': 1,
                                                           'maximum': 500}},
                                  'live': False},
             'security_strategy': {'name': 'security_strategy',
                                   'path': '/securities/{ticker}/options/strategy',
                                   'parameters': {'ticker': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'Exact listed '
                                                                            'underlying (e.g. '
                                                                            'GOOG, GOOGL, BRK-A, '
                                                                            'or BRK-B). A listing '
                                                                            'never falls through '
                                                                            'to its sibling; dot '
                                                                            'class-share spelling '
                                                                            'such as BRK.B is '
                                                                            'accepted as BRK-B.'},
                                                  'leg': {'location': 'query',
                                                          'required': False,
                                                          'type': 'array',
                                                          'description': 'One leg as OCC symbol, '
                                                                         'side and optional '
                                                                         'quantity (default 1, max '
                                                                         '100), e.g. '
                                                                         'O:AAPL261120C00270000,long,1. '
                                                                         'Repeat for up to four '
                                                                         'legs.'}},
                                   'live': False},
             'security_summary': {'name': 'security_summary',
                                  'path': '/securities/{ticker}/options/summary',
                                  'parameters': {'ticker': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Exact listed '
                                                                           'underlying (e.g. GOOG, '
                                                                           'GOOGL, BRK-A, or '
                                                                           'BRK-B). A listing '
                                                                           'never falls through to '
                                                                           'its sibling; dot '
                                                                           'class-share spelling '
                                                                           'such as BRK.B is '
                                                                           'accepted as BRK-B.'},
                                                 'expiration': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'Expiration date, '
                                                                               'YYYY-MM-DD '
                                                                               '(default: nearest '
                                                                               'upcoming).',
                                                                'format': 'date'}},
                                  'live': False},
             'security_term_structure': {'name': 'security_term_structure',
                                         'path': '/securities/{ticker}/options/term-structure',
                                         'parameters': {'ticker': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': 'Exact listed '
                                                                                  'underlying '
                                                                                  '(e.g. GOOG, '
                                                                                  'GOOGL, BRK-A, '
                                                                                  'or BRK-B). A '
                                                                                  'listing never '
                                                                                  'falls through '
                                                                                  'to its sibling; '
                                                                                  'dot class-share '
                                                                                  'spelling such '
                                                                                  'as BRK.B is '
                                                                                  'accepted as '
                                                                                  'BRK-B.'},
                                                        'maxExpirations': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'integer',
                                                                           'description': 'Expirations '
                                                                                          'to '
                                                                                          'compare '
                                                                                          '(default: '
                                                                                          '8, max: '
                                                                                          '12).',
                                                                           'default': 8,
                                                                           'maximum': 12}},
                                         'live': False},
             'security_volatility': {'name': 'security_volatility',
                                     'path': '/securities/{ticker}/options/volatility',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Exact listed '
                                                                              'underlying (e.g. '
                                                                              'GOOG, GOOGL, BRK-A, '
                                                                              'or BRK-B). A '
                                                                              'listing never falls '
                                                                              'through to its '
                                                                              'sibling; dot '
                                                                              'class-share '
                                                                              'spelling such as '
                                                                              'BRK.B is accepted '
                                                                              'as BRK-B.'},
                                                    'startDate': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'string',
                                                                  'description': 'First session, '
                                                                                 'YYYY-MM-DD '
                                                                                 '(default: a year '
                                                                                 'before endDate).',
                                                                  'format': 'date'},
                                                    'endDate': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'Last session, '
                                                                               'YYYY-MM-DD '
                                                                               '(default: today).',
                                                                'format': 'date'},
                                                    'limit': {'location': 'query',
                                                              'required': False,
                                                              'type': 'integer',
                                                              'description': 'Maximum sessions to '
                                                                             'return, newest first '
                                                                             '(default: 250, max: '
                                                                             '500).',
                                                              'default': 250,
                                                              'minimum': 1,
                                                              'maximum': 500}},
                                     'live': False},
             'chain': {'name': 'chain',
                       'path': '/stocks/{ticker}/options/chain',
                       'parameters': {'ticker': {'location': 'path',
                                                 'required': True,
                                                 'type': 'string',
                                                 'description': 'Exact listed underlying (e.g. '
                                                                'GOOG, GOOGL, BRK-A, or BRK-B), or '
                                                                'MIC:TICKER for a TSX or TSXV '
                                                                'listing (e.g. XTSE:RY). A listing '
                                                                'never falls through to its '
                                                                'sibling; dot class-share spelling '
                                                                'such as BRK.B is accepted as '
                                                                'BRK-B.'},
                                      'expiration': {'location': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'Expiration date in YYYY-MM-DD '
                                                                    'format (default: nearest '
                                                                    'upcoming).',
                                                     'format': 'date'},
                                      'minStrike': {'location': 'query',
                                                    'required': False,
                                                    'type': 'number',
                                                    'description': 'Only include strikes at or '
                                                                   'above this price.'},
                                      'maxStrike': {'location': 'query',
                                                    'required': False,
                                                    'type': 'number',
                                                    'description': 'Only include strikes at or '
                                                                   'below this price.'},
                                      'type': {'location': 'query',
                                               'required': False,
                                               'type': 'string',
                                               'description': 'Contract type filter: call or put '
                                                              '(default: both).'},
                                      'limit': {'location': 'query',
                                                'required': False,
                                                'type': 'integer',
                                                'description': 'Maximum contracts to return, taken '
                                                               'nearest the money (default: 250, '
                                                               'max: 500).',
                                                'default': 250,
                                                'minimum': 1,
                                                'maximum': 500}},
                       'live': False},
             'contract': {'name': 'contract',
                          'path': '/stocks/{ticker}/options/contract',
                          'parameters': {'ticker': {'location': 'path',
                                                    'required': True,
                                                    'type': 'string',
                                                    'description': 'Exact listed underlying (e.g. '
                                                                   'GOOG, GOOGL, BRK-A, or BRK-B), '
                                                                   'or MIC:TICKER for a TSX or '
                                                                   'TSXV listing (e.g. XTSE:RY). A '
                                                                   'listing never falls through to '
                                                                   'its sibling; dot class-share '
                                                                   'spelling such as BRK.B is '
                                                                   'accepted as BRK-B.'},
                                         'symbol': {'location': 'query',
                                                    'required': False,
                                                    'type': 'string',
                                                    'description': 'OCC option symbol (e.g. '
                                                                   'O:AAPL260724C00110000).'}},
                          'live': False},
             'contract_bars': {'name': 'contract_bars',
                               'path': '/stocks/{ticker}/options/contract/bars',
                               'parameters': {'ticker': {'location': 'path',
                                                         'required': True,
                                                         'type': 'string',
                                                         'description': 'Exact listed underlying '
                                                                        '(e.g. GOOG, GOOGL, BRK-A, '
                                                                        'or BRK-B), or XNSE:SYMBOL '
                                                                        'for an NSE share or index '
                                                                        '(e.g. XNSE:RELIANCE, '
                                                                        'XNSE:NIFTY). A listing '
                                                                        'never falls through to '
                                                                        'its sibling; dot '
                                                                        'class-share spelling such '
                                                                        'as BRK.B is accepted as '
                                                                        'BRK-B.'},
                                              'symbol': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'OCC option symbol (e.g. '
                                                                        'O:AAPL270617C00350000). '
                                                                        'An NSE contract is O:, '
                                                                        "NSE's symbol, the expiry "
                                                                        'as yyMMdd, C or P, then '
                                                                        'the strike times 1000 in '
                                                                        'at least eight digits '
                                                                        '(e.g. '
                                                                        'O:NIFTY261117P25100000); '
                                                                        'percent-encode an '
                                                                        'ampersand in it (M&M is '
                                                                        'M%26M).'},
                                              'timeframe': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Bar size: day, hour or '
                                                                           'minute (default: '
                                                                           'day).'},
                                              'startDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'First date, YYYY-MM-DD '
                                                                           '(default depends on '
                                                                           'timeframe).',
                                                            'format': 'date'},
                                              'endDate': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'Last date, YYYY-MM-DD '
                                                                         '(default: today).',
                                                          'format': 'date'},
                                              'limit': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Maximum bars to return, '
                                                                       'newest first (default: '
                                                                       '250, max: 500).',
                                                        'default': 250,
                                                        'minimum': 1,
                                                        'maximum': 500}},
                               'live': False},
             'contract_trades': {'name': 'contract_trades',
                                 'path': '/stocks/{ticker}/options/contract/trades',
                                 'parameters': {'ticker': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': 'Exact listed underlying '
                                                                          '(e.g. GOOG, GOOGL, '
                                                                          'BRK-A, or BRK-B). A '
                                                                          'listing never falls '
                                                                          'through to its sibling; '
                                                                          'dot class-share '
                                                                          'spelling such as BRK.B '
                                                                          'is accepted as BRK-B.'},
                                                'symbol': {'location': 'query',
                                                           'required': False,
                                                           'type': 'string',
                                                           'description': 'OCC option symbol (e.g. '
                                                                          'O:AAPL270617C00350000).'},
                                                'startDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'First date, '
                                                                             'YYYY-MM-DD (default: '
                                                                             '4 days before end).',
                                                              'format': 'date'},
                                                'endDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Last date, YYYY-MM-DD '
                                                                           '(default: today).',
                                                            'format': 'date'},
                                                'endTime': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': 'Last time to include, '
                                                                           'RFC 3339; replaces '
                                                                           'endDate. To continue a '
                                                                           'truncated read, pass '
                                                                           "the oldest row's time, "
                                                                           'which can come back '
                                                                           'again.',
                                                            'format': 'timestamp'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum trades to '
                                                                         'return, newest first '
                                                                         '(default: 250, max: '
                                                                         '500).',
                                                          'default': 250,
                                                          'minimum': 1,
                                                          'maximum': 500}},
                                 'live': False},
             'expirations': {'name': 'expirations',
                             'path': '/stocks/{ticker}/options/expirations',
                             'parameters': {'ticker': {'location': 'path',
                                                       'required': True,
                                                       'type': 'string',
                                                       'description': 'Exact listed underlying '
                                                                      '(e.g. GOOG, GOOGL, BRK-A, '
                                                                      'or BRK-B), or MIC:TICKER '
                                                                      'for a TSX or TSXV listing '
                                                                      '(e.g. XTSE:RY). A listing '
                                                                      'never falls through to its '
                                                                      'sibling; dot class-share '
                                                                      'spelling such as BRK.B is '
                                                                      'accepted as BRK-B.'},
                                            'expired': {'location': 'query',
                                                        'required': False,
                                                        'type': 'boolean',
                                                        'description': 'List past expirations '
                                                                       'instead of upcoming ones '
                                                                       '(US listings only).',
                                                        'default': False},
                                            'startDate': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': 'With expired=true: first '
                                                                         'expiration date, '
                                                                         'YYYY-MM-DD (default: 90 '
                                                                         'days before end).',
                                                          'format': 'date'},
                                            'endDate': {'location': 'query',
                                                        'required': False,
                                                        'type': 'string',
                                                        'description': 'With expired=true: last '
                                                                       'expiration date, '
                                                                       'YYYY-MM-DD (default: '
                                                                       'yesterday).',
                                                        'format': 'date'}},
                             'live': False},
             'session': {'name': 'session',
                         'path': '/stocks/{ticker}/options/session',
                         'parameters': {'ticker': {'location': 'path',
                                                   'required': True,
                                                   'type': 'string',
                                                   'description': 'Exact listed underlying (e.g. '
                                                                  'GOOG, GOOGL, BRK-A, or BRK-B). '
                                                                  'A listing never falls through '
                                                                  'to its sibling; dot class-share '
                                                                  'spelling such as BRK.B is '
                                                                  'accepted as BRK-B.'},
                                        'date': {'location': 'query',
                                                 'required': False,
                                                 'type': 'string',
                                                 'description': 'The session, YYYY-MM-DD.',
                                                 'format': 'date'},
                                        'expiration': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'The expiration, YYYY-MM-DD.',
                                                       'format': 'date'},
                                        'minStrike': {'location': 'query',
                                                      'required': False,
                                                      'type': 'number',
                                                      'description': 'Only include strikes at or '
                                                                     'above this price.'},
                                        'maxStrike': {'location': 'query',
                                                      'required': False,
                                                      'type': 'number',
                                                      'description': 'Only include strikes at or '
                                                                     'below this price.'},
                                        'type': {'location': 'query',
                                                 'required': False,
                                                 'type': 'string',
                                                 'description': 'Contract type filter: call or put '
                                                                '(default: both).'},
                                        'limit': {'location': 'query',
                                                  'required': False,
                                                  'type': 'integer',
                                                  'description': 'Maximum contracts to return, '
                                                                 "taken nearest the session's "
                                                                 'stock close (default: 250, max: '
                                                                 '500).',
                                                  'default': 250,
                                                  'minimum': 1,
                                                  'maximum': 500}},
                         'live': False},
             'strategy': {'name': 'strategy',
                          'path': '/stocks/{ticker}/options/strategy',
                          'parameters': {'ticker': {'location': 'path',
                                                    'required': True,
                                                    'type': 'string',
                                                    'description': 'Exact listed underlying (e.g. '
                                                                   'GOOG, GOOGL, BRK-A, or BRK-B). '
                                                                   'A listing never falls through '
                                                                   'to its sibling; dot '
                                                                   'class-share spelling such as '
                                                                   'BRK.B is accepted as BRK-B.'},
                                         'leg': {'location': 'query',
                                                 'required': False,
                                                 'type': 'array',
                                                 'description': 'One leg as OCC symbol, side and '
                                                                'optional quantity (default 1, max '
                                                                '100), e.g. '
                                                                'O:AAPL261120C00270000,long,1. '
                                                                'Repeat for up to four legs.'}},
                          'live': False},
             'summary': {'name': 'summary',
                         'path': '/stocks/{ticker}/options/summary',
                         'parameters': {'ticker': {'location': 'path',
                                                   'required': True,
                                                   'type': 'string',
                                                   'description': 'Exact listed underlying (e.g. '
                                                                  'GOOG, GOOGL, BRK-A, or BRK-B). '
                                                                  'A listing never falls through '
                                                                  'to its sibling; dot class-share '
                                                                  'spelling such as BRK.B is '
                                                                  'accepted as BRK-B.'},
                                        'expiration': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Expiration date, YYYY-MM-DD '
                                                                      '(default: nearest '
                                                                      'upcoming).',
                                                       'format': 'date'}},
                         'live': False},
             'term_structure': {'name': 'term_structure',
                                'path': '/stocks/{ticker}/options/term-structure',
                                'parameters': {'ticker': {'location': 'path',
                                                          'required': True,
                                                          'type': 'string',
                                                          'description': 'Exact listed underlying '
                                                                         '(e.g. GOOG, GOOGL, '
                                                                         'BRK-A, or BRK-B). A '
                                                                         'listing never falls '
                                                                         'through to its sibling; '
                                                                         'dot class-share spelling '
                                                                         'such as BRK.B is '
                                                                         'accepted as BRK-B.'},
                                               'maxExpirations': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Expirations to '
                                                                                 'compare '
                                                                                 '(default: 8, '
                                                                                 'max: 12).',
                                                                  'default': 8,
                                                                  'maximum': 12}},
                                'live': False},
             'volatility': {'name': 'volatility',
                            'path': '/stocks/{ticker}/options/volatility',
                            'parameters': {'ticker': {'location': 'path',
                                                      'required': True,
                                                      'type': 'string',
                                                      'description': 'Exact listed underlying '
                                                                     '(e.g. GOOG, GOOGL, BRK-A, or '
                                                                     'BRK-B). A listing never '
                                                                     'falls through to its '
                                                                     'sibling; dot class-share '
                                                                     'spelling such as BRK.B is '
                                                                     'accepted as BRK-B.'},
                                           'startDate': {'location': 'query',
                                                         'required': False,
                                                         'type': 'string',
                                                         'description': 'First session, YYYY-MM-DD '
                                                                        '(default: a year before '
                                                                        'endDate).',
                                                         'format': 'date'},
                                           'endDate': {'location': 'query',
                                                       'required': False,
                                                       'type': 'string',
                                                       'description': 'Last session, YYYY-MM-DD '
                                                                      '(default: today).',
                                                       'format': 'date'},
                                           'limit': {'location': 'query',
                                                     'required': False,
                                                     'type': 'integer',
                                                     'description': 'Maximum sessions to return, '
                                                                    'newest first (default: 250, '
                                                                    'max: 500).',
                                                     'default': 250,
                                                     'minimum': 1,
                                                     'maximum': 500}},
                            'live': False}},
 'international': {'canadian_fund_holdings': {'name': 'canadian_fund_holdings',
                                              'path': '/stocks/{exchange}/{ticker}/canadian-fund-holdings',
                                              'parameters': {'exchange': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'string',
                                                                          'description': ''},
                                                             'ticker': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'string',
                                                                        'description': ''},
                                                             'limit': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': '',
                                                                       'default': 20},
                                                             'offset': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': '',
                                                                        'default': 0}},
                                              'live': False},
                   'director_transactions': {'name': 'director_transactions',
                                             'path': '/stocks/{exchange}/{ticker}/director-transactions',
                                             'parameters': {'exchange': {'location': 'path',
                                                                         'required': True,
                                                                         'type': 'string',
                                                                         'description': ''},
                                                            'ticker': {'location': 'path',
                                                                       'required': True,
                                                                       'type': 'string',
                                                                       'description': ''},
                                                            'limit': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': '',
                                                                      'default': 20}},
                                             'live': False},
                   'european_fund_holdings': {'name': 'european_fund_holdings',
                                              'path': '/stocks/{exchange}/{ticker}/european-fund-holdings',
                                              'parameters': {'exchange': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'string',
                                                                          'description': ''},
                                                             'ticker': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'string',
                                                                        'description': ''},
                                                             'limit': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': '',
                                                                       'default': 20},
                                                             'offset': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': '',
                                                                        'default': 0},
                                                             'periodEnd': {'location': 'query',
                                                                           'required': False,
                                                                           'type': 'string',
                                                                           'description': '',
                                                                           'format': 'date'}},
                                              'live': False},
                   'filings': {'name': 'filings',
                               'path': '/stocks/{exchange}/{ticker}/filings',
                               'parameters': {'exchange': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': ''},
                                              'ticker': {'location': 'path',
                                                         'required': True,
                                                         'type': 'string',
                                                         'description': ''},
                                              'q': {'location': 'query',
                                                    'required': False,
                                                    'type': 'string',
                                                    'description': ''},
                                              'startDate': {'location': 'query',
                                                            'required': False,
                                                            'type': 'string',
                                                            'description': '',
                                                            'format': 'date'},
                                              'endDate': {'location': 'query',
                                                          'required': False,
                                                          'type': 'string',
                                                          'description': '',
                                                          'format': 'date'},
                                              'limit': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': '',
                                                        'default': 20},
                                              'offset': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': '',
                                                         'default': 0}},
                               'live': False},
                   'financial_reports': {'name': 'financial_reports',
                                         'path': '/stocks/{exchange}/{ticker}/financial-reports',
                                         'parameters': {'exchange': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'string',
                                                                     'description': ''},
                                                        'ticker': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': ''},
                                                        'limit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': '',
                                                                  'default': 20}},
                                         'live': False},
                   'financial_reports_native': {'name': 'financial_reports_native',
                                                'path': '/stocks/{exchange}/{ticker}/financial-reports/native',
                                                'parameters': {'exchange': {'location': 'path',
                                                                            'required': True,
                                                                            'type': 'string',
                                                                            'description': ''},
                                                               'ticker': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'string',
                                                                          'description': ''},
                                                               'offset': {'location': 'query',
                                                                          'required': False,
                                                                          'type': 'integer',
                                                                          'description': '',
                                                                          'default': 0},
                                                               'limit': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': '',
                                                                         'default': 20}},
                                                'live': False},
                   'native_financial_report': {'name': 'native_financial_report',
                                               'path': '/stocks/{exchange}/{ticker}/financial-reports/native/{reportId}',
                                               'parameters': {'exchange': {'location': 'path',
                                                                           'required': True,
                                                                           'type': 'string',
                                                                           'description': ''},
                                                              'ticker': {'location': 'path',
                                                                         'required': True,
                                                                         'type': 'string',
                                                                         'description': ''},
                                                              'reportId': {'location': 'path',
                                                                           'required': True,
                                                                           'type': 'string',
                                                                           'description': '',
                                                                           'format': 'uuid'},
                                                              'offset': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'integer',
                                                                         'description': '',
                                                                         'default': 0},
                                                              'limit': {'location': 'query',
                                                                        'required': False,
                                                                        'type': 'integer',
                                                                        'description': '',
                                                                        'default': 100}},
                                               'live': False},
                   'government_contracts': {'name': 'government_contracts',
                                            'path': '/stocks/{exchange}/{ticker}/government-contracts',
                                            'parameters': {'exchange': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'string',
                                                                        'description': 'The '
                                                                                       "listing's "
                                                                                       'market '
                                                                                       'identifier '
                                                                                       'code, e.g. '
                                                                                       'XTSE.'},
                                                           'ticker': {'location': 'path',
                                                                      'required': True,
                                                                      'type': 'string',
                                                                      'description': 'The '
                                                                                     "listing's "
                                                                                     'ticker on '
                                                                                     'that '
                                                                                     'exchange, '
                                                                                     'e.g. WJX.'},
                                                           'startDate': {'location': 'query',
                                                                         'required': False,
                                                                         'type': 'string',
                                                                         'description': 'Start '
                                                                                        'action '
                                                                                        'date '
                                                                                        '(yyyy-MM-dd, '
                                                                                        'defaults '
                                                                                        'to 1 year '
                                                                                        'ago).',
                                                                         'format': 'date'},
                                                           'endDate': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'End action '
                                                                                      'date '
                                                                                      '(yyyy-MM-dd, '
                                                                                      'defaults to '
                                                                                      'today).',
                                                                       'format': 'date'},
                                                           'limit': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Maximum rows '
                                                                                    'to return '
                                                                                    '(1–500; '
                                                                                    'default '
                                                                                    'varies per '
                                                                                    'endpoint).',
                                                                     'minimum': 1,
                                                                     'maximum': 500},
                                                           'offset': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': 'Rows to skip '
                                                                                     'before the '
                                                                                     'first '
                                                                                     'returned row '
                                                                                     '(default '
                                                                                     '0).'},
                                                           'agency': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'Optional '
                                                                                     'case-insensitive '
                                                                                     'substring '
                                                                                     'filter on '
                                                                                     'awarding '
                                                                                     'agency.'},
                                                           'sortBy': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'string',
                                                                      'description': 'Sort by '
                                                                                     'amount '
                                                                                     '(default) or '
                                                                                     'date.',
                                                                      'default': 'amount'},
                                                           'country': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'string',
                                                                       'description': 'Awarding '
                                                                                      'government: '
                                                                                      'US or CA; '
                                                                                      'defaults to '
                                                                                      'the '
                                                                                      "listing's "
                                                                                      'country (CA '
                                                                                      'for a '
                                                                                      'Canadian '
                                                                                      'listing, '
                                                                                      'else US).'}},
                                            'live': False},
                   'insider_transactions': {'name': 'insider_transactions',
                                            'path': '/stocks/{exchange}/{ticker}/insider-transactions',
                                            'parameters': {'exchange': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'string',
                                                                        'description': ''},
                                                           'ticker': {'location': 'path',
                                                                      'required': True,
                                                                      'type': 'string',
                                                                      'description': ''},
                                                           'limit': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': '',
                                                                     'default': 20},
                                                           'offset': {'location': 'query',
                                                                      'required': False,
                                                                      'type': 'integer',
                                                                      'description': '',
                                                                      'default': 0}},
                                            'live': False},
                   'major_holdings': {'name': 'major_holdings',
                                      'path': '/stocks/{exchange}/{ticker}/major-holdings',
                                      'parameters': {'exchange': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': ''},
                                                     'ticker': {'location': 'path',
                                                                'required': True,
                                                                'type': 'string',
                                                                'description': ''},
                                                     'limit': {'location': 'query',
                                                               'required': False,
                                                               'type': 'integer',
                                                               'description': '',
                                                               'default': 20},
                                                     'offset': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': '',
                                                                'default': 0}},
                                      'live': False},
                   'public_short_positions': {'name': 'public_short_positions',
                                              'path': '/stocks/{exchange}/{ticker}/public-short-positions',
                                              'parameters': {'exchange': {'location': 'path',
                                                                          'required': True,
                                                                          'type': 'string',
                                                                          'description': ''},
                                                             'ticker': {'location': 'path',
                                                                        'required': True,
                                                                        'type': 'string',
                                                                        'description': ''},
                                                             'limit': {'location': 'query',
                                                                       'required': False,
                                                                       'type': 'integer',
                                                                       'description': '',
                                                                       'default': 20}},
                                              'live': False},
                   'short_disclosures': {'name': 'short_disclosures',
                                         'path': '/stocks/{exchange}/{ticker}/short-disclosures',
                                         'parameters': {'exchange': {'location': 'path',
                                                                     'required': True,
                                                                     'type': 'string',
                                                                     'description': ''},
                                                        'ticker': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': ''},
                                                        'limit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': '',
                                                                  'default': 20},
                                                        'source': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'string',
                                                                   'description': '',
                                                                   'default': 'AMF-France'}},
                                         'live': False},
                   'short_positions': {'name': 'short_positions',
                                       'path': '/stocks/{exchange}/{ticker}/short-positions',
                                       'parameters': {'exchange': {'location': 'path',
                                                                   'required': True,
                                                                   'type': 'string',
                                                                   'description': ''},
                                                      'ticker': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': ''},
                                                      'limit': {'location': 'query',
                                                                'required': False,
                                                                'type': 'integer',
                                                                'description': '',
                                                                'default': 24},
                                                      'offset': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': '',
                                                                 'default': 0}},
                                       'live': False}},
 'company': {'profile': {'name': 'profile',
                         'path': '/stocks/{ticker}',
                         'parameters': {'ticker': {'location': 'path',
                                                   'required': True,
                                                   'type': 'string',
                                                   'description': 'Exact listed ticker (e.g. AAPL '
                                                                  'or BRK-B), or MIC:TICKER for a '
                                                                  'listing on another exchange '
                                                                  '(e.g. XETR:SIE).'}},
                         'live': False},
             'analyst_estimates': {'name': 'analyst_estimates',
                                   'path': '/stocks/{ticker}/analyst-estimates',
                                   'parameters': {'ticker': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'Stock ticker symbol '
                                                                            '(e.g. AAPL), or '
                                                                            'MIC:TICKER for a '
                                                                            'company listed on '
                                                                            'another exchange '
                                                                            '(e.g. XAMS:ASML).'},
                                                  'metric': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Exact source metric '
                                                                            'label to keep (up to '
                                                                            '512 characters).'},
                                                  'period': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Exact source period '
                                                                            'label to keep (up to '
                                                                            '256 characters).'},
                                                  'dimensions': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'Exact source '
                                                                                'dimension labels '
                                                                                'to keep (up to '
                                                                                '1024 '
                                                                                'characters).'},
                                                  'snapshotId': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'string',
                                                                 'description': 'A verified '
                                                                                'snapshot ID '
                                                                                'returned in '
                                                                                'snapshots.',
                                                                 'format': 'uuid'},
                                                  'asOf': {'location': 'query',
                                                           'required': False,
                                                           'type': 'string',
                                                           'description': 'ISO-8601 cutoff; the '
                                                                          'snapshot must have been '
                                                                          'verified by that '
                                                                          'instant.',
                                                           'format': 'timestamp'},
                                                  'snapshotOffset': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Snapshot-history '
                                                                                    'offset '
                                                                                    '(default 0, '
                                                                                    '0-100000); '
                                                                                    'pages hold up '
                                                                                    'to 10 '
                                                                                    'snapshots.',
                                                                     'default': 0,
                                                                     'minimum': 0,
                                                                     'maximum': 100000},
                                                  'limit': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Observations to return '
                                                                           '(default 100, 1-100).',
                                                            'default': 100,
                                                            'minimum': 1,
                                                            'maximum': 100},
                                                  'offset': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Zero-based '
                                                                            'observation offset '
                                                                            '(default 0, '
                                                                            '0-100000).',
                                                             'default': 0,
                                                             'minimum': 0,
                                                             'maximum': 100000}},
                                   'live': False},
             'atm_programs': {'name': 'atm_programs',
                              'path': '/stocks/{ticker}/atm-programs',
                              'parameters': {'ticker': {'location': 'path',
                                                        'required': True,
                                                        'type': 'string',
                                                        'description': 'Stock ticker symbol (e.g. '
                                                                       'AAPL).'}},
                              'live': False},
             'buyback_programs': {'name': 'buyback_programs',
                                  'path': '/stocks/{ticker}/buyback-programs',
                                  'parameters': {'ticker': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Stock ticker symbol '
                                                                           '(e.g. AAPL), or '
                                                                           'MIC:TICKER for a '
                                                                           'company listed on '
                                                                           'another exchange (e.g. '
                                                                           'XTSE:WDO).'}},
                                  'live': False},
             'customer_concentration': {'name': 'customer_concentration',
                                        'path': '/stocks/{ticker}/customer-concentration',
                                        'parameters': {'ticker': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Stock ticker '
                                                                                 'symbol (e.g. '
                                                                                 'AAPL).'}},
                                        'live': False},
             'debt_profile': {'name': 'debt_profile',
                              'path': '/stocks/{ticker}/debt-profile',
                              'parameters': {'ticker': {'location': 'path',
                                                        'required': True,
                                                        'type': 'string',
                                                        'description': 'Stock ticker symbol (e.g. '
                                                                       'AAPL), or MIC:TICKER for a '
                                                                       'company listed on another '
                                                                       'exchange (e.g. '
                                                                       'XAMS:ASML).'},
                                             'instrumentLimit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum '
                                                                                'instruments to '
                                                                                'return (default '
                                                                                '25, max 100).',
                                                                 'default': 25,
                                                                 'maximum': 100},
                                             'instrumentOffset': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Zero-based '
                                                                                 'instrument '
                                                                                 'offset.',
                                                                  'default': 0,
                                                                  'minimum': 0},
                                             'reportedTotalLimit': {'location': 'query',
                                                                    'required': False,
                                                                    'type': 'integer',
                                                                    'description': 'Maximum '
                                                                                   'issuer-reported '
                                                                                   'totals to '
                                                                                   'return '
                                                                                   '(default 25, '
                                                                                   'max 100).',
                                                                    'default': 25,
                                                                    'maximum': 100},
                                             'reportedTotalOffset': {'location': 'query',
                                                                     'required': False,
                                                                     'type': 'integer',
                                                                     'description': 'Zero-based '
                                                                                    'issuer-reported-total '
                                                                                    'offset.',
                                                                     'default': 0,
                                                                     'minimum': 0}},
                              'live': False},
             'executive_changes': {'name': 'executive_changes',
                                   'path': '/stocks/{ticker}/executive-changes',
                                   'parameters': {'ticker': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'Stock ticker symbol '
                                                                            '(e.g. AAPL).'},
                                                  'action': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Optional action '
                                                                            'filter: Appointed, '
                                                                            'Resigned, Terminated, '
                                                                            'or Retired.'},
                                                  'startDate': {'location': 'query',
                                                                'required': False,
                                                                'type': 'string',
                                                                'description': 'Optional oldest '
                                                                               'filed date '
                                                                               '(yyyy-MM-dd).',
                                                                'format': 'date'},
                                                  'endDate': {'location': 'query',
                                                              'required': False,
                                                              'type': 'string',
                                                              'description': 'Optional newest '
                                                                             'filed date '
                                                                             '(yyyy-MM-dd).',
                                                              'format': 'date'},
                                                  'limit': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Maximum changes to '
                                                                           'return (default 25, '
                                                                           'max 100; zero or '
                                                                           'negative values are '
                                                                           'rejected, values above '
                                                                           'the maximum are '
                                                                           'clamped).',
                                                            'minimum': 1,
                                                            'maximum': 100},
                                                  'offset': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Changes to skip '
                                                                            'before the first '
                                                                            'returned one (default '
                                                                            '0) ; pages past the '
                                                                            'per-request cap.'}},
                                   'live': False},
             'executive_compensation': {'name': 'executive_compensation',
                                        'path': '/stocks/{ticker}/executive-compensation',
                                        'parameters': {'ticker': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'Stock ticker '
                                                                                 'symbol (e.g. '
                                                                                 'AAPL).'},
                                                       'years': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum fiscal '
                                                                                'years to return, '
                                                                                'newest first '
                                                                                '(default all on '
                                                                                'file; values '
                                                                                'below 1 are a '
                                                                                '400).',
                                                                 'minimum': 1}},
                                        'live': False},
             'exempt_offerings': {'name': 'exempt_offerings',
                                  'path': '/stocks/{ticker}/exempt-offerings',
                                  'parameters': {'ticker': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'Company ticker symbol '
                                                                           '(e.g. AAPL).'},
                                                 'startDate': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Earliest filing '
                                                                              'date (yyyy-MM-dd).',
                                                               'format': 'date'},
                                                 'endDate': {'location': 'query',
                                                             'required': False,
                                                             'type': 'string',
                                                             'description': 'Latest filing date '
                                                                            '(yyyy-MM-dd).',
                                                             'format': 'date'},
                                                 'limit': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Maximum rows to return '
                                                                          '(1–500; default varies '
                                                                          'per endpoint).',
                                                           'minimum': 1,
                                                           'maximum': 500},
                                                 'offset': {'location': 'query',
                                                            'required': False,
                                                            'type': 'integer',
                                                            'description': 'Rows to skip before '
                                                                           'the first returned row '
                                                                           '(default 0).'}},
                                  'live': False},
             'going_concern': {'name': 'going_concern',
                               'path': '/stocks/{ticker}/going-concern',
                               'parameters': {'ticker': {'location': 'path',
                                                         'required': True,
                                                         'type': 'string',
                                                         'description': 'Stock ticker symbol (e.g. '
                                                                        'AAPL).'}},
                               'live': False},
             'guidance': {'name': 'guidance',
                          'path': '/stocks/{ticker}/guidance',
                          'parameters': {'ticker': {'location': 'path',
                                                    'required': True,
                                                    'type': 'string',
                                                    'description': 'Stock ticker symbol (e.g. '
                                                                   'AAPL), or MIC:TICKER for a '
                                                                   'company listed on another '
                                                                   'exchange (e.g. XAMS:ASML).'},
                                         'maxReleases': {'location': 'query',
                                                         'required': False,
                                                         'type': 'integer',
                                                         'description': 'Optional: only the newest '
                                                                        'N releases (1 or more; '
                                                                        'values above 200 read as '
                                                                        '200). Omitted, every '
                                                                        'release on file is '
                                                                        'returned.'},
                                         'fiscalYear': {'location': 'query',
                                                        'required': False,
                                                        'type': 'integer',
                                                        'description': 'Optional: only guidance '
                                                                       'for a period in that '
                                                                       'fiscal year of the '
                                                                       "company's own calendar, "
                                                                       'from every release that '
                                                                       'gave it.'}},
                          'live': False},
             'kpis': {'name': 'kpis',
                      'path': '/stocks/{ticker}/kpis',
                      'parameters': {'ticker': {'location': 'path',
                                                'required': True,
                                                'type': 'string',
                                                'description': 'Stock ticker symbol (e.g. AAPL).'},
                                     'metric': {'location': 'query',
                                                'required': False,
                                                'type': 'string',
                                                'description': 'Optional metric name to return on '
                                                               'its own (case-insensitive; matches '
                                                               "the company's own labels). Omit "
                                                               'for every metric. An ambiguous '
                                                               'name that matches several metrics '
                                                               'is a 400 listing the candidates; a '
                                                               'name matching nothing is a 404 '
                                                               'listing everything on file.'}},
                      'live': False},
             'non_gaap_bridge': {'name': 'non_gaap_bridge',
                                 'path': '/stocks/{ticker}/non-gaap-bridge',
                                 'parameters': {'ticker': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': 'Stock ticker symbol '
                                                                          '(e.g. AAPL).'},
                                                'limit': {'location': 'query',
                                                          'required': False,
                                                          'type': 'integer',
                                                          'description': 'Maximum rows to return '
                                                                         '(1–500; default varies '
                                                                         'per endpoint).',
                                                          'minimum': 1,
                                                          'maximum': 500},
                                                'offset': {'location': 'query',
                                                           'required': False,
                                                           'type': 'integer',
                                                           'description': 'Rows to skip before the '
                                                                          'first returned row '
                                                                          '(default 0).'}},
                                 'live': False},
             'revenue_breakdown': {'name': 'revenue_breakdown',
                                   'path': '/stocks/{ticker}/revenue-breakdown',
                                   'parameters': {'ticker': {'location': 'path',
                                                             'required': True,
                                                             'type': 'string',
                                                             'description': 'Stock ticker symbol '
                                                                            '(e.g. AAPL), or '
                                                                            'MIC:TICKER for a '
                                                                            'company listed on '
                                                                            'another exchange '
                                                                            '(e.g. XAMS:ASML).'}},
                                   'live': False},
             'valuation_multiples': {'name': 'valuation_multiples',
                                     'path': '/stocks/{ticker}/valuation-multiples',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Stock ticker symbol '
                                                                              '(e.g. AAPL).'}},
                                     'live': False},
             'valuation_multiples_history': {'name': 'valuation_multiples_history',
                                             'path': '/stocks/{ticker}/valuation-multiples/history',
                                             'parameters': {'ticker': {'location': 'path',
                                                                       'required': True,
                                                                       'type': 'string',
                                                                       'description': 'Stock '
                                                                                      'ticker '
                                                                                      'symbol '
                                                                                      '(e.g. '
                                                                                      'AAPL).'}},
                                             'live': False},
             'financial_statement': {'name': 'financial_statement',
                                     'path': '/stocks/{ticker}/financial-statements/{statement}',
                                     'parameters': {'ticker': {'location': 'path',
                                                               'required': True,
                                                               'type': 'string',
                                                               'description': 'Stock ticker symbol '
                                                                              '(e.g. AAPL), or '
                                                                              'MIC:TICKER for a '
                                                                              'company listed on '
                                                                              'another exchange '
                                                                              '(e.g. XAMS:ASML).'},
                                                    'statement': {'location': 'path',
                                                                  'required': True,
                                                                  'type': 'string',
                                                                  'description': 'income, balance, '
                                                                                 'or cashflow. The '
                                                                                 'aliases is, pnl, '
                                                                                 'bs, and cf also '
                                                                                 'work.'},
                                                    'year': {'location': 'query',
                                                             'required': False,
                                                             'type': 'integer',
                                                             'description': 'Optional fiscal year. '
                                                                            'Omit with period to '
                                                                            'use the latest '
                                                                            'available period.'},
                                                    'period': {'location': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Optional fiscal '
                                                                              'period: FY or Q1 '
                                                                              'through Q4.'}},
                                     'live': False},
             'financial_facts': {'name': 'financial_facts',
                                 'path': '/stocks/{ticker}/financial-facts/{concept}',
                                 'parameters': {'ticker': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': 'Stock ticker symbol '
                                                                          '(e.g. AAPL), or '
                                                                          'MIC:TICKER for a '
                                                                          'company listed on '
                                                                          'another exchange (e.g. '
                                                                          'XAMS:ASML).'},
                                                'concept': {'location': 'path',
                                                            'required': True,
                                                            'type': 'string',
                                                            'description': 'A supported concept '
                                                                           'alias such as revenue, '
                                                                           'net-income, '
                                                                           'eps-diluted, '
                                                                           'total-assets, or '
                                                                           'operating-cash-flow.'}},
                                 'live': False},
             'debt_instrument': {'name': 'debt_instrument',
                                 'path': '/stocks/{ticker}/debt-instruments/{instrumentId}',
                                 'parameters': {'ticker': {'location': 'path',
                                                           'required': True,
                                                           'type': 'string',
                                                           'description': 'Stock ticker symbol '
                                                                          '(e.g. AAPL), or '
                                                                          'MIC:TICKER for a '
                                                                          'company listed on '
                                                                          'another exchange (e.g. '
                                                                          'XAMS:ASML).'},
                                                'instrumentId': {'location': 'path',
                                                                 'required': True,
                                                                 'type': 'string',
                                                                 'description': 'Debt instrument '
                                                                                'identifier '
                                                                                'returned by the '
                                                                                'debt-profile '
                                                                                'endpoint.',
                                                                 'format': 'uuid'},
                                                'historyLimit': {'location': 'query',
                                                                 'required': False,
                                                                 'type': 'integer',
                                                                 'description': 'Maximum '
                                                                                'filing-history '
                                                                                'rows to return '
                                                                                '(default 25, max '
                                                                                '100).',
                                                                 'default': 25,
                                                                 'maximum': 100},
                                                'historyOffset': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Zero-based '
                                                                                 'filing-history '
                                                                                 'offset.',
                                                                  'default': 0,
                                                                  'minimum': 0},
                                                'covenantLimit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Maximum covenant '
                                                                                 'rows to return '
                                                                                 '(default 25, max '
                                                                                 '100).',
                                                                  'default': 25,
                                                                  'maximum': 100},
                                                'covenantOffset': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Zero-based '
                                                                                  'covenant '
                                                                                  'offset.',
                                                                   'default': 0,
                                                                   'minimum': 0},
                                                'documentLimit': {'location': 'query',
                                                                  'required': False,
                                                                  'type': 'integer',
                                                                  'description': 'Maximum '
                                                                                 'governing-document '
                                                                                 'rows to return '
                                                                                 '(default 25, max '
                                                                                 '100).',
                                                                  'default': 25,
                                                                  'maximum': 100},
                                                'documentOffset': {'location': 'query',
                                                                   'required': False,
                                                                   'type': 'integer',
                                                                   'description': 'Zero-based '
                                                                                  'governing-document '
                                                                                  'offset.',
                                                                   'default': 0,
                                                                   'minimum': 0}},
                                 'live': False}}}

def operations(family: str) -> tuple[str, ...]:
    """Return the exact dataset names accepted by one family tool."""
    return tuple(CATALOG.get(family, {}))


def choices() -> list[str]:
    """Return the sorted enumeration of every supported family."""
    return sorted(CATALOG)


def _date(value: str, name: str) -> str:
    """Return a validated ISO calendar date with no silent substitution."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    return value


def _timestamp(value: str, name: str) -> str:
    """Return an ISO-8601 timestamp after parsing, preserving its exact text."""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    return value


def _identifier(value: Any, name: str, item: Mapping[str, Any]) -> str:
    """Return bounded text; forbid URL separators only in path placeholders."""
    text = str(value).strip()
    if not text or len(text) > 2000 or "\x00" in text:
        raise ValueError(f"{name} must be non-empty text of at most 2000 characters")
    if item["location"] == "path" and re.search(r"(?:%2f|%5c|[?#/\\])", text.lower()):
        raise ValueError(f"{name} must be a safe single path segment")
    return text


def _number(value: Any, name: str, item: Mapping[str, Any]) -> int | float:
    """Return a finite, typed numeric filter inside its documented bounds."""
    kind = item["type"]
    if isinstance(value, bool):
        raise ValueError(f"{name} must be {kind}, not boolean")
    if kind == "integer" and not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if kind == "number" and not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if result < item.get("minimum", -math.inf) or result > item.get("maximum", math.inf):
        raise ValueError(f"{name} is outside the documented bounds for this dataset")
    return int(result) if kind == "integer" else result


def _filter_value(name: str, value: Any, item: Mapping[str, Any]) -> Any:
    """Validate one filter and return its type-preserving REST value."""
    if value is None:
        return None
    kind = item["type"]
    if kind in ("integer", "number"):
        return _number(value, name, item)
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        return value
    if kind == "array":
        if not isinstance(value, (list, tuple)) or not value or len(value) > 200:
            raise ValueError(f"{name} must be a non-empty bounded list")
        return [str(part).strip() for part in value]
    text = _identifier(value, name, item)
    if item.get("format") == "date":
        _date(text, name)
    elif item.get("format") == "timestamp":
        _timestamp(text, name)
    elif item.get("format") == "uuid":
        try:
            uuid.UUID(text)
        except ValueError as exc:
            raise ValueError(f"{name} must be a UUID returned by Equibles") from exc
    if item.get("choices") and text not in item["choices"]:
        raise ValueError(f"{name} has a value outside its documented enumeration: {text}")
    return text


def compile_call(
    family: str, dataset: str, filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a concrete allowlisted route and sanitized exact-name parameters.

    Every path placeholder is required by construction. Unknown families,
    datasets and query keys are refused before the caller can reach transport.
    CSV variants are refused because the common response requires JSON.
    """
    if not family or family not in CATALOG:
        raise ValueError("family must be one of " + ", ".join(sorted(CATALOG)))
    if not dataset or dataset not in CATALOG[family]:
        raise ValueError("dataset must be one of " + ", ".join(operations(family)))
    entry = CATALOG[family][dataset]
    if filters is None:
        filters = {}
    if not isinstance(filters, Mapping) or any(not isinstance(key, str) for key in filters):
        raise ValueError("filters must be a JSON object with documented parameter names")
    parameters = entry["parameters"]
    unknown = set(filters) - set(parameters)
    if unknown:
        raise ValueError(f"unsupported filters for {dataset}: {sorted(unknown)}")
    applied = {
        name: _filter_value(name, filters.get(name), item)
        for name, item in parameters.items()
    }
    if str(applied.get("format") or "").lower() == "csv":
        raise ValueError("binary/CSV output is outside this JSON tool")
    missing = [
        name for name, item in parameters.items()
        if item.get("required") and applied.get(name) is None
    ]
    if missing:
        raise ValueError(f"missing required filters for {dataset}: {missing}")
    if "query" in parameters and "isin" in parameters and "exchange" in parameters:
        exclusive = [
            name for name in ("query", "isin", "exchange", "market")
            if applied.get(name) is not None
        ]
        if len(exclusive) > 1:
            raise ValueError(
                "query, isin, exchange and market are mutually exclusive listing filters"
            )
    path = entry["path"]
    for name, item in parameters.items():
        if item["location"] == "path":
            path = path.replace("{" + name + "}", str(applied[name]))
    if re.search(r"[{}]", path):
        raise ValueError("every required path identifier must be supplied")
    if {"startLine", "endLine"} <= set(parameters):
        start = applied.get("startLine")
        end = applied.get("endLine")
        if start is not None and end is not None and (
            start > end or end - start >= 500
        ):
            raise ValueError(
                "filing line window must start at or before endLine and span at most 500 lines"
            )
    return {
        "family": family,
        "dataset": dataset,
        "path": path,
        "params": {
            name: applied[name]
            for name, item in parameters.items()
            if item["location"] == "query" and applied[name] is not None
        },
        "live": entry["live"],
    }


__all__ = ["CATALOG", "choices", "compile_call", "operations"]
