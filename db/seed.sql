-- ============================================================
-- SAP AI Agent — Real-World Seed Data
-- Company: Bharat Precision Industries Ltd (BPIL)
-- Industry: Capital goods — industrial automation, CNC machines,
--            precision components, control panels
-- HQ: Pune, Maharashtra | FY 2024-25
-- Run against: sap_agent database (PostgreSQL)
-- ============================================================

-- ── Plants ─────────────────────────────────────────────────────────────────────
INSERT INTO plants (plant_id, name, city, country) VALUES
('1000', 'Mumbai Logistics Hub',       'Mumbai',      'India'),
('1100', 'Pune Manufacturing Plant',   'Pune',        'India'),
('1200', 'Chennai Assembly Unit',      'Chennai',     'India'),
('1300', 'Bengaluru Tech Centre',      'Bengaluru',   'India'),
('2000', 'Delhi Distribution Centre',  'New Delhi',   'India'),
('2100', 'Ahmedabad Warehouse',        'Ahmedabad',   'India'),
('3000', 'Hyderabad R&D Centre',       'Hyderabad',   'India'),
('4000', 'Kolkata Regional Office',    'Kolkata',     'India')
ON CONFLICT (plant_id) DO UPDATE SET name = EXCLUDED.name;

-- ── GL Accounts ────────────────────────────────────────────────────────────────
INSERT INTO gl_accounts (gl_account, name, account_type, balance, currency) VALUES
('400001', 'IT Services & Software Expense',    'EXPENSE',    42500000.00,  'INR'),
('400002', 'Raw Material Purchases',            'EXPENSE',   182600000.00,  'INR'),
('400003', 'Utilities — Power & Fuel',          'EXPENSE',    14200000.00,  'INR'),
('400004', 'Salaries, Wages & Bonus',           'EXPENSE',   248000000.00,  'INR'),
('400005', 'Rent & Facility Charges',           'EXPENSE',    18500000.00,  'INR'),
('400006', 'Manufacturing Overhead',            'EXPENSE',    64800000.00,  'INR'),
('400007', 'Depreciation — Plant & Machinery',  'EXPENSE',    32400000.00,  'INR'),
('400008', 'Repair & Maintenance',              'EXPENSE',     8700000.00,  'INR'),
('400009', 'Quality Control & Inspection',      'EXPENSE',     6200000.00,  'INR'),
('400010', 'Selling & Distribution Expense',    'EXPENSE',    22100000.00,  'INR'),
('100001', 'Cash & Bank Balances',              'ASSET',      98500000.00,  'INR'),
('100002', 'Accounts Receivable — Trade',       'ASSET',     145200000.00,  'INR'),
('100003', 'Inventory — Raw Materials',         'ASSET',      68400000.00,  'INR'),
('100004', 'Work-in-Progress Inventory',        'ASSET',      38200000.00,  'INR'),
('100005', 'Finished Goods Inventory',          'ASSET',      52600000.00,  'INR'),
('100006', 'Fixed Assets — Gross Block',        'ASSET',     620000000.00,  'INR'),
('100007', 'Less: Accumulated Depreciation',    'ASSET',    -185000000.00,  'INR'),
('200001', 'Accounts Payable — Trade',          'LIABILITY', 112700000.00,  'INR'),
('200002', 'Advance from Customers',            'LIABILITY',  24800000.00,  'INR'),
('300001', 'Share Capital',                     'EQUITY',    500000000.00,  'INR'),
('300002', 'Retained Earnings',                 'EQUITY',    186400000.00,  'INR')
ON CONFLICT (gl_account) DO UPDATE SET balance = EXCLUDED.balance;

-- ── Vendors ─────────────────────────────────────────────────────────────────────
INSERT INTO vendors (vendor_id, name, city, country, payment_terms, bank_account, bank_name, tax_id, currency, status) VALUES
-- IT & Consulting vendors
('V001', 'Tata Consultancy Services Ltd',          'Mumbai',    'India', 'NET30', '123456789012', 'HDFC Bank',     '27AAACT2727Q1ZZ', 'INR', 'ACTIVE'),
('V002', 'Infosys BPM Limited',                    'Bengaluru', 'India', 'NET45', '987654321098', 'ICICI Bank',    '29AABCI1234F1ZQ', 'INR', 'ACTIVE'),
('V003', 'Wipro Technologies Ltd',                 'Bengaluru', 'India', 'NET30', '112233445566', 'Axis Bank',     '29AAACW4396H1ZL', 'INR', 'ACTIVE'),
('V004', 'HCL Technologies Ltd',                   'Noida',     'India', 'NET60', '223344556677', 'SBI',           '09AAACH3990G1ZD', 'INR', 'ACTIVE'),
('V005', 'Tech Mahindra Ltd',                      'Pune',      'India', 'NET30', '334455667788', 'Kotak Bank',    '27AABCT1332L1ZB', 'INR', 'ACTIVE'),
-- Industrial & Engineering vendors
('V006', 'Larsen & Toubro Ltd',                    'Mumbai',    'India', 'NET45', '556677889900', 'ICICI Bank',    '27AAACL0111L1ZA', 'INR', 'ACTIVE'),
('V007', 'Siemens India Ltd',                      'Mumbai',    'India', 'NET30', '667788990011', 'Deutsche Bank', '27AAACS0810K1ZU', 'INR', 'ACTIVE'),
('V008', 'ABB India Ltd',                          'Bengaluru', 'India', 'NET45', '778899001122', 'SBI',           '29AAACA0429B1ZS', 'INR', 'ACTIVE'),
('V009', 'Bosch Ltd',                              'Bengaluru', 'India', 'NET30', '889900112233', 'HDFC Bank',     '29AAACB0911C1Z5', 'INR', 'ACTIVE'),
-- Raw material & components vendors
('V010', 'SKF India Ltd',                          'Pune',      'India', 'NET30', '990011223344', 'Citi Bank',     '27AAACS8274P1ZF', 'INR', 'ACTIVE'),
('V011', 'Bharat Forge Ltd',                       'Pune',      'India', 'NET45', '101112131415', 'HDFC Bank',     '27AAACB6034P1ZD', 'INR', 'ACTIVE'),
('V012', 'Kirloskar Brothers Ltd',                 'Pune',      'India', 'NET60', '121314151617', 'ICICI Bank',    '27AAACK4083N1ZP', 'INR', 'ACTIVE'),
('V013', 'Thermax Ltd',                            'Pune',      'India', 'NET45', '131415161718', 'Axis Bank',     '27AAACT5784G1ZT', 'INR', 'ACTIVE'),
('V014', 'Parker Hannifin India Pvt Ltd',          'Mumbai',    'India', 'NET30', '141516171819', 'Citi Bank',     '27AAACP6543H1ZX', 'INR', 'ACTIVE'),
('V015', 'Atlas Copco (India) Pvt Ltd',            'Pune',      'India', 'NET45', '151617181920', 'Deutsche Bank', '27AAACA7892K1ZM', 'INR', 'ACTIVE'),
('V016', 'Schneider Electric India Pvt Ltd',       'Bengaluru', 'India', 'NET30', '161718192021', 'SBI',           '29AAACS6721J1ZN', 'INR', 'ACTIVE'),
('V017', 'Timken India Ltd',                       'Bengaluru', 'India', 'NET45', '171819202122', 'HSBC',          '29AAACT8901M1ZQ', 'INR', 'ACTIVE'),
('V018', 'Eaton India Pvt Ltd',                    'Pune',      'India', 'NET30', '181920212223', 'HDFC Bank',     '27AAACE5432L1ZV', 'INR', 'ACTIVE'),
('V019', 'Festo India Pvt Ltd',                    'Bengaluru', 'India', 'NET45', '192021222324', 'ICICI Bank',    '29AAACF4321K1ZR', 'INR', 'ACTIVE'),
('V020', 'Havells India Ltd',                      'Noida',     'India', 'NET30', '202122232425', 'Kotak Bank',    '09AAACH7654N1ZS', 'INR', 'ACTIVE'),
-- Software & Cloud vendors
('V021', 'Oracle India Pvt Ltd',                   'Bengaluru', 'India', 'NET60', '990011223344', 'Citi Bank',     '29AAACP7185C1ZN', 'INR', 'BLOCKED'),
('V022', 'Microsoft India Pvt Ltd',                'Hyderabad', 'India', 'NET30', '101112131415', 'HSBC',          '36AAACP5245C1ZN', 'INR', 'ACTIVE'),
('V023', 'SAP India Pvt Ltd',                      'Bengaluru', 'India', 'NET60', '232425262728', 'Deutsche Bank', '29AAACS9012D1ZP', 'INR', 'ACTIVE'),
('V024', 'Reliance Industries Ltd',                'Mumbai',    'India', 'NET15', '445566778899', 'HDFC Bank',     '27AAACR5055K1ZT', 'INR', 'ACTIVE'),
('V025', 'Elgi Equipments Ltd',                    'Coimbatore','India', 'NET45', '252627282930', 'SBI',           '33AAACE4321F1ZW', 'INR', 'ACTIVE')
ON CONFLICT (vendor_id) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status;

-- ── Cost Centers ────────────────────────────────────────────────────────────────
INSERT INTO cost_centers (cost_center_id, name, department, budget, actual, currency, fiscal_year) VALUES
('CC100', 'Information Technology',         'IT',          25000000.00,  18750000.00, 'INR', 2024),
('CC120', 'IT Security & Compliance',       'IT',           8500000.00,   6200000.00, 'INR', 2024),
('CC200', 'Finance & Accounts',             'Finance',     12000000.00,   9800000.00, 'INR', 2024),
('CC300', 'Human Resources',               'HR',            8500000.00,   7200000.00, 'INR', 2024),
('CC400', 'Manufacturing Operations',       'Production',  45000000.00,  41200000.00, 'INR', 2024),
('CC410', 'Quality Assurance',              'Production',  12000000.00,  10800000.00, 'INR', 2024),
('CC420', 'Tool Room & Maintenance',        'Production',  15000000.00,  13200000.00, 'INR', 2024),
('CC500', 'Sales & Marketing',              'Sales',       30000000.00,  27800000.00, 'INR', 2024),
('CC600', 'Research & Development',         'R&D',         20000000.00,  15600000.00, 'INR', 2024),
('CC610', 'Product Design & Engineering',   'R&D',         18000000.00,  14200000.00, 'INR', 2024),
('CC700', 'Supply Chain & Logistics',       'SCM',         18000000.00,  16900000.00, 'INR', 2024),
('CC800', 'Customer Support',               'Support',      6500000.00,   5400000.00, 'INR', 2024),
('CC900', 'Administration',                 'Admin',        5000000.00,   4100000.00, 'INR', 2024),
('CC110', 'IT Infrastructure',              'IT',          15000000.00,  12300000.00, 'INR', 2024),
('CC430', 'Painting & Surface Treatment',   'Production',   9000000.00,   8400000.00, 'INR', 2024)
ON CONFLICT (cost_center_id) DO UPDATE SET actual = EXCLUDED.actual;

-- ── Invoices ────────────────────────────────────────────────────────────────────
INSERT INTO invoices (invoice_id, vendor_id, amount, currency, status, due_date, po_id, posting_date, gl_account) VALUES
-- FY 2024-25 Q1 (Apr-Jun 2024)
('INV-2024-0001', 'V001', 4500000.00, 'INR', 'PAID',    '2024-05-31', 'PO3001', '2024-04-30', '400001'),
('INV-2024-0002', 'V002', 2800000.00, 'INR', 'PAID',    '2024-06-30', 'PO3002', '2024-06-01', '400001'),
('INV-2024-0003', 'V010', 3200000.00, 'INR', 'PAID',    '2024-06-15', 'PO3003', '2024-05-15', '400002'),
-- Q2 (Jul-Sep 2024)
('INV-2024-0004', 'V007', 6200000.00, 'INR', 'PAID',    '2024-08-20', 'PO3004', '2024-07-20', '400002'),
('INV-2024-0005', 'V011', 4800000.00, 'INR', 'PAID',    '2024-09-10', 'PO3005', '2024-08-10', '400002'),
('INV-2024-0006', 'V022', 8700000.00, 'INR', 'PAID',    '2024-09-30', 'PO3006', '2024-09-01', '400001'),
-- Q3 (Oct-Dec 2024)
('INV-2024-0007', 'V003', 5100000.00, 'INR', 'PAID',    '2024-11-30', 'PO3007', '2024-10-30', '400001'),
('INV-2024-0008', 'V009', 2200000.00, 'INR', 'PAID',    '2024-12-01', 'PO3008', '2024-11-01', '400002'),
('INV-2024-0009', 'V016', 4800000.00, 'INR', 'PARTIAL', '2024-12-31', 'PO3009', '2024-11-30', '400002'),
('INV-2024-0010', 'V008', 3600000.00, 'INR', 'OPEN',    '2025-01-15', 'PO3010', '2024-12-15', '400002'),
-- Q4 (Jan-Mar 2025)
('INV-2025-0001', 'V001', 4500000.00, 'INR', 'OPEN',    '2025-02-28', 'PO3011', '2025-01-20', '400001'),
('INV-2025-0002', 'V004', 1950000.00, 'INR', 'OVERDUE', '2025-01-05', 'PO3012', '2024-12-05', '400001'),
('INV-2025-0003', 'V005', 3400000.00, 'INR', 'OPEN',    '2025-03-31', 'PO3013', '2025-01-28', '400001'),
('INV-2025-0004', 'V006', 9800000.00, 'INR', 'OPEN',    '2025-03-15', 'PO3014', '2025-02-15', '400002'),
('INV-2025-0005', 'V010', 2600000.00, 'INR', 'OPEN',    '2025-03-20', 'PO3015', '2025-02-20', '400002'),
('INV-2025-0006', 'V013', 7400000.00, 'INR', 'OPEN',    '2025-04-05', 'PO3016', '2025-03-05', '400002'),
('INV-2025-0007', 'V015', 5200000.00, 'INR', 'OPEN',    '2025-04-10', 'PO3017', '2025-03-10', '400006'),
('INV-2025-0008', 'V017', 3100000.00, 'INR', 'OPEN',    '2025-04-20', 'PO3018', '2025-03-20', '400002'),
('INV-2025-0009', 'V021', 2400000.00, 'INR', 'BLOCKED', '2025-01-31', 'PO3019', '2025-01-01', '400001'),
('INV-2025-0010', 'V023', 18000000.00,'INR', 'OPEN',    '2025-06-30', 'PO3020', '2025-03-01', '400001'),
('INV-2025-0011', 'V018', 4100000.00, 'INR', 'OPEN',    '2025-04-30', 'PO3021', '2025-03-01', '400006'),
('INV-2025-0012', 'V019', 2800000.00, 'INR', 'OPEN',    '2025-04-15', 'PO3022', '2025-03-15', '400006'),
('INV-2024-0011', 'V011', 6500000.00, 'INR', 'PAID',    '2024-10-31', 'PO3023', '2024-09-30', '400002'),
('INV-2024-0012', 'V012', 4200000.00, 'INR', 'PAID',    '2024-11-15', 'PO3024', '2024-10-15', '400002'),
('INV-2024-0013', 'V014', 3800000.00, 'INR', 'PAID',    '2024-12-20', 'PO3025', '2024-11-20', '400002'),
('INV-2025-0013', 'V020', 1900000.00, 'INR', 'OPEN',    '2025-03-31', 'PO3026', '2025-02-28', '400006'),
('INV-2025-0014', 'V024', 22000000.00,'INR', 'OPEN',    '2025-04-15', 'PO3027', '2025-03-01', '400003'),
('INV-2024-0014', 'V025', 5600000.00, 'INR', 'PAID',    '2024-08-31', 'PO3028', '2024-07-31', '400006'),
('INV-2025-0015', 'V009', 4800000.00, 'INR', 'OPEN',    '2025-05-15', 'PO3029', '2025-03-15', '400002'),
('INV-2025-0016', 'V007', 8200000.00, 'INR', 'OPEN',    '2025-04-30', 'PO3030', '2025-03-01', '400006')
ON CONFLICT (invoice_id) DO UPDATE SET status = EXCLUDED.status, amount = EXCLUDED.amount;

-- ── Materials ───────────────────────────────────────────────────────────────────
INSERT INTO materials (material_id, description, material_type, unit, price, currency, weight_kg, category, hsn_code) VALUES
-- Finished goods (FERT)
('MAT001', 'Industrial Server Rack 42U 800mm Deep',         'FERT', 'EA',    185000.00, 'INR',  45.000, 'IT Hardware',        '84715020'),
('MAT011', 'Industrial Robot Arm 6-Axis 20kg Payload',      'FERT', 'EA',   2800000.00, 'INR', 320.000, 'Automation',         '84790090'),
('MAT012', 'Solar Panel 400W Monocrystalline PERC',         'FERT', 'EA',     18500.00, 'INR',  22.000, 'Energy',             '85414011'),
('MAT015', 'PLC Siemens S7-1500 CPU 1515-2 PN',             'FERT', 'EA',    185000.00, 'INR',   3.500, 'Automation',         '85371090'),
('MAT020', 'Variable Frequency Drive 15kW 3Ph 415V',        'FERT', 'EA',    145000.00, 'INR',   8.200, 'Automation',         '85044090'),
('MAT022', 'Industrial Gearbox Helical 50:1 Ratio 11kW',    'FERT', 'EA',    320000.00, 'INR',  82.000, 'Power Transmission',  '84834090'),
('MAT025', 'Touch Screen HMI 10in 1024x600 WVGA IP65',      'FERT', 'EA',     68000.00, 'INR',   1.200, 'Automation',         '85177090'),
('MAT028', 'Safety PLC Siemens S7-1200F CPU 1214FC',        'FERT', 'EA',    215000.00, 'INR',   0.650, 'Automation',         '85371090'),
('MAT034', 'DC Motor Controller 48V 200A Regenerative',     'FERT', 'EA',     95000.00, 'INR',   3.800, 'Automation',         '85044090'),
-- Semi-finished goods (HALB)
('MAT002', 'Laptop Computer Core i7 16GB 512GB SSD',        'FERT', 'EA',     92000.00, 'INR',   2.100, 'IT Hardware',        '84713010'),
('MAT009', 'Control Panel Assembly 400V 100A MCC',          'HALB', 'EA',     42000.00, 'INR',  12.000, 'Electrical',         '85372090'),
('MAT016', 'CNC Turned Shaft EN24T 40mm x 300mm',           'HALB', 'EA',      8500.00, 'INR',   2.800, 'Precision Parts',    '84839090'),
('MAT021', 'Helical Gear Set Module 3 Z=40/20 Steel',       'HALB', 'SET',    42000.00, 'INR',  14.000, 'Power Transmission',  '84833090'),
('MAT026', 'Aluminium Die-Cast Housing IP65 220x180x110',   'HALB', 'EA',     12500.00, 'INR',   1.850, 'Enclosures',         '76069290'),
-- Raw materials (ROH)
('MAT003', 'Copper Cable 1.5 sqmm 100m FRLS Roll',          'ROH',  'ROL',     8500.00, 'INR',  18.000, 'Electrical',         '85444290'),
('MAT004', 'Industrial Motor 3Ph 50HP 1450 RPM TEFC',       'ROH',  'EA',    125000.00, 'INR', 180.000, 'Machinery',          '85012090'),
('MAT005', 'MS Steel Sheet HR 3mm x 1250 x 2500mm IS 2062', 'ROH',  'EA',      4200.00, 'INR',  73.000, 'Raw Material',       '72082700'),
('MAT006', 'Hydraulic Pump Gear Type 200 bar 40 LPM',       'ROH',  'EA',     68000.00, 'INR',  22.000, 'Hydraulics',         '84136090'),
('MAT007', 'HDPE Pipe SDR11 110mm PN10 6m',                 'ROH',  'EA',      3800.00, 'INR',   8.500, 'Plumbing',           '39172310'),
('MAT008', 'Deep Groove Ball Bearing SKF 6205-2RS',          'ROH',  'EA',       380.00, 'INR',   0.120, 'Bearings',           '84821010'),
('MAT010', 'SAP S/4HANA Enterprise License Annual',         'DIEN', 'EA',  12000000.00, 'INR',   0.000, 'Software',           '99030000'),
('MAT013', 'Cement OPC 53 Grade 50kg Bag Ultratech',        'ROH',  'BAG',      480.00, 'INR',  50.000, 'Construction',       '25232910'),
('MAT014', 'Aluminium T-Slot Profile 40x40mm 2000mm',       'ROH',  'EA',      2800.00, 'INR',   4.200, 'Raw Material',       '76042910'),
('MAT017', 'M16 x 80mm High-Tensile Bolt Grade 8.8 (Pack10)', 'ROH','PKT',      420.00, 'INR',   1.200, 'Fasteners',          '73181500'),
('MAT018', 'SS 316L Seamless Pipe 50mm OD 3mm WT 6m',       'ROH',  'EA',     18500.00, 'INR',  22.000, 'Raw Material',       '73049090'),
('MAT019', 'Pneumatic Cylinder ISO 15552 100mm Bore 200mm', 'ROH',  'EA',      8200.00, 'INR',   2.400, 'Pneumatics',         '84123110'),
('MAT023', 'Nitrile O-Ring AS568-A 50x3.5mm (Pack50)',      'ROH',  'PKT',       280.00, 'INR',   0.050, 'Seals',              '40169300'),
('MAT024', 'Inductive Proximity Sensor M18 10mm NPN NO 2m', 'ROH',  'EA',      1850.00, 'INR',   0.120, 'Sensors',            '85365090'),
('MAT027', 'Servo Motor 750W 3000RPM 220VAC Flange Mount',  'ROH',  'EA',     42000.00, 'INR',   3.200, 'Drives',             '85012090'),
('MAT029', 'Industrial Ethernet Switch 8-Port PoE Managed', 'ROH',  'EA',     18500.00, 'INR',   1.400, 'Networking',         '85176200'),
('MAT030', 'Carbide Insert SNMG 120408-MR P25 CVD Coated',  'ROH',  'EA',       480.00, 'INR',   0.020, 'Cutting Tools',      '82090020'),
('MAT031', 'Deep Groove Ball Bearing 6308-2Z 40x90x23mm',   'ROH',  'EA',      1200.00, 'INR',   0.680, 'Bearings',           '84821010'),
('MAT032', 'Hydraulic Oil Servo 46 ISO VG 46 210L Barrel',  'ROH',  'LT',      180.00, 'INR',   0.870, 'Lubricants',         '27101920'),
('MAT033', 'SS 304 Hex Bolt M8 x 25mm + Nut Kit (Pack100)', 'ROH',  'PKT',      680.00, 'INR',   1.600, 'Fasteners',          '73181500'),
('MAT035', 'Conveyor Belt EP200/2 1000mm Width 5m',         'ROH',  'EA',     24000.00, 'INR',  18.000, 'Conveying',          '59101000'),
('MAT036', 'EN8 Ground Shaft 50mm Dia 1000mm Length',       'ROH',  'EA',      6800.00, 'INR',  15.000, 'Raw Material',       '72283090'),
('MAT037', '3-Phase Contactor 65A 415V AC Coil',            'ROH',  'EA',      2400.00, 'INR',   0.820, 'Switchgear',         '85366100'),
('MAT038', 'SS 304 Flange ANSI B16.5 Class 150 DN50 4Hole', 'ROH',  'EA',      4200.00, 'INR',   3.200, 'Pipe Fittings',      '73079990'),
('MAT039', 'Linear Guide Rail HGR20 1000mm with 2 Blocks',  'ROH',  'EA',      8500.00, 'INR',   2.400, 'Linear Motion',      '84828090'),
('MAT040', 'GI Cable Tray Perforated 200x50mm 3m Length',   'ROH',  'EA',      1850.00, 'INR',   5.600, 'Electrical',         '73269099')
ON CONFLICT (material_id) DO UPDATE SET price = EXCLUDED.price, description = EXCLUDED.description;

-- ── Stock ────────────────────────────────────────────────────────────────────────
INSERT INTO stock (material_id, plant, unrestricted, reserved, in_transit, reorder_point) VALUES
('MAT001', '1000',   12.000,   2.000,   0.000,    5.000),
('MAT002', '1000',   45.000,   5.000,   3.000,   10.000),
('MAT002', '1300',   20.000,   0.000,   0.000,    8.000),
('MAT003', '1000',  850.000,  50.000, 100.000,  200.000),
('MAT004', '1100',    8.000,   1.000,   0.000,    3.000),
('MAT005', '1100',  320.000,  40.000,   0.000,  100.000),
('MAT006', '1100',    4.000,   0.000,   2.000,    2.000),
('MAT007', '1000',  120.000,  20.000,   0.000,   30.000),
('MAT008', '1000', 2400.000, 300.000,   0.000,  500.000),
('MAT008', '1100',  800.000, 100.000, 200.000,  200.000),
('MAT009', '1000',   18.000,   3.000,   0.000,    5.000),
('MAT010', '1300',    2.000,   0.000,   0.000,    1.000),
('MAT011', '1100',    3.000,   1.000,   0.000,    2.000),
('MAT012', '1200',  250.000,  50.000, 100.000,   60.000),
('MAT013', '1000', 1500.000, 200.000, 500.000,  400.000),
('MAT014', '1000',  480.000,  60.000,   0.000,  100.000),
('MAT015', '1000',    6.000,   1.000,   0.000,    2.000),
('MAT015', '1300',    4.000,   0.000,   2.000,    2.000),
('MAT017', '1100', 1200.000, 150.000, 300.000,  400.000),
('MAT018', '1100',   48.000,   8.000,  12.000,   20.000),
('MAT019', '1100',   35.000,   5.000,  10.000,   15.000),
('MAT020', '1000',   12.000,   2.000,   4.000,    5.000),
('MAT021', '1100',   22.000,   4.000,   0.000,   10.000),
('MAT023', '1100', 5000.000, 500.000,   0.000, 2000.000),
('MAT024', '1000',  180.000,  20.000,  50.000,   60.000),
('MAT027', '1100',   14.000,   2.000,   6.000,    8.000),
('MAT029', '1300',   28.000,   0.000,  10.000,   10.000),
('MAT030', '1100', 3500.000, 400.000, 1000.000,1500.000),
('MAT031', '1100',  620.000,  80.000, 120.000,  200.000),
('MAT032', '1100',  840.000, 100.000, 210.000,  300.000),
('MAT033', '1100', 2200.000, 300.000, 600.000,  800.000),
('MAT035', '1100',   42.000,   6.000,   5.000,   15.000),
('MAT036', '1100',  180.000,  25.000,  40.000,   60.000),
('MAT037', '1000',  320.000,  40.000,  80.000,  100.000),
('MAT039', '1100',   24.000,   4.000,   8.000,   10.000),
('MAT040', '1000',  560.000,  60.000, 100.000,  200.000)
ON CONFLICT (material_id, plant) DO UPDATE SET
    unrestricted  = EXCLUDED.unrestricted,
    reserved      = EXCLUDED.reserved,
    in_transit    = EXCLUDED.in_transit,
    reorder_point = EXCLUDED.reorder_point;

-- ── Purchase Orders ─────────────────────────────────────────────────────────────
INSERT INTO purchase_orders (po_id, vendor_id, material_id, qty, unit, price, currency, status, delivery_date, plant) VALUES
('PO3001', 'V001', 'MAT010',    2.000, 'EA',  12000000.00, 'INR', 'RECEIVED',  '2024-06-30', '1300'),
('PO3002', 'V002', 'MAT002',   50.000, 'EA',    92000.00,  'INR', 'RECEIVED',  '2024-06-15', '1000'),
('PO3003', 'V010', 'MAT008', 2000.000, 'EA',      380.00,  'INR', 'RECEIVED',  '2024-06-10', '1000'),
('PO3004', 'V007', 'MAT009',   20.000, 'EA',    42000.00,  'INR', 'RECEIVED',  '2024-08-10', '1000'),
('PO3005', 'V011', 'MAT005',  400.000, 'EA',     4200.00,  'INR', 'RECEIVED',  '2024-08-15', '1100'),
('PO3006', 'V022', 'MAT002',   30.000, 'EA',    92000.00,  'INR', 'RECEIVED',  '2024-09-20', '1000'),
('PO3007', 'V003', 'MAT004',    8.000, 'EA',   125000.00,  'INR', 'RECEIVED',  '2024-10-30', '1100'),
('PO3008', 'V009', 'MAT006',    6.000, 'EA',    68000.00,  'INR', 'RECEIVED',  '2024-11-10', '1100'),
('PO3009', 'V016', 'MAT020',   10.000, 'EA',   145000.00,  'INR', 'RECEIVED',  '2024-12-01', '1000'),
('PO3010', 'V008', 'MAT009',   25.000, 'EA',    42000.00,  'INR', 'OPEN',      '2025-01-20', '1000'),
('PO3011', 'V001', 'MAT010',    1.000, 'EA',  12000000.00, 'INR', 'OPEN',      '2025-03-31', '1300'),
('PO3012', 'V004', 'MAT002',   20.000, 'EA',    92000.00,  'INR', 'OPEN',      '2025-01-10', '1000'),
('PO3013', 'V005', 'MAT015',    5.000, 'EA',   185000.00,  'INR', 'OPEN',      '2025-02-28', '1000'),
('PO3014', 'V006', 'MAT011',    2.000, 'EA',  2800000.00,  'INR', 'OPEN',      '2025-04-30', '1100'),
('PO3015', 'V010', 'MAT031',  500.000, 'EA',    1200.00,   'INR', 'OPEN',      '2025-03-15', '1100'),
('PO3016', 'V013', 'MAT035',   20.000, 'EA',   24000.00,   'INR', 'OPEN',      '2025-04-10', '1100'),
('PO3017', 'V015', 'MAT032',  500.000, 'LT',     180.00,   'INR', 'IN_TRANSIT','2025-03-25', '1100'),
('PO3018', 'V017', 'MAT031',  300.000, 'EA',    1200.00,   'INR', 'OPEN',      '2025-04-25', '1100'),
('PO3019', 'V021', 'MAT010',    1.000, 'EA',  12000000.00, 'INR', 'CANCELLED', '2025-01-15', '1300'),
('PO3020', 'V023', 'MAT010',    2.000, 'EA',   9000000.00, 'INR', 'OPEN',      '2025-06-30', '1300'),
('PO3021', 'V018', 'MAT020',    8.000, 'EA',   145000.00,  'INR', 'OPEN',      '2025-04-20', '1000'),
('PO3022', 'V019', 'MAT019',   50.000, 'EA',    8200.00,   'INR', 'OPEN',      '2025-04-10', '1100'),
('PO3023', 'V011', 'MAT005',  600.000, 'EA',    4200.00,   'INR', 'RECEIVED',  '2024-10-05', '1100'),
('PO3024', 'V012', 'MAT006',    8.000, 'EA',   68000.00,   'INR', 'RECEIVED',  '2024-10-20', '1100'),
('PO3025', 'V014', 'MAT019',   80.000, 'EA',    8200.00,   'INR', 'RECEIVED',  '2024-11-25', '1100'),
('PO3026', 'V020', 'MAT037',  200.000, 'EA',    2400.00,   'INR', 'OPEN',      '2025-03-30', '1000'),
('PO3027', 'V024', 'MAT032',  1050.000,'LT',     180.00,   'INR', 'OPEN',      '2025-04-15', '1100'),
('PO3028', 'V025', 'MAT036',  100.000, 'EA',    6800.00,   'INR', 'RECEIVED',  '2024-08-15', '1100'),
('PO3029', 'V009', 'MAT038',   60.000, 'EA',    4200.00,   'INR', 'OPEN',      '2025-05-20', '1100'),
('PO3030', 'V007', 'MAT028',    4.000, 'EA',   215000.00,  'INR', 'OPEN',      '2025-04-30', '1000')
ON CONFLICT (po_id) DO UPDATE SET status = EXCLUDED.status;

-- ── Customers ───────────────────────────────────────────────────────────────────
INSERT INTO customers (customer_id, name, city, country, credit_limit, payment_terms, email, phone, currency, status, gst_number) VALUES
('C001', 'Mahindra & Mahindra Ltd',              'Mumbai',    'India',  50000000.00, 'NET30', 'procurement@mahindra.com',       '+91-22-24958220', 'INR', 'ACTIVE', '27AABCM8027E1ZA'),
('C002', 'Bajaj Auto Ltd',                       'Pune',      'India',  35000000.00, 'NET45', 'purchase@bajaj.com',             '+91-20-27472851', 'INR', 'ACTIVE', '27AAACB4517H1ZV'),
('C003', 'Maruti Suzuki India Ltd',              'Gurugram',  'India',  80000000.00, 'NET30', 'vendor@maruti.com',              '+91-124-4882785', 'INR', 'ACTIVE', '06AAACM3025E1ZP'),
('C004', 'NTPC Limited',                         'New Delhi', 'India',  60000000.00, 'NET60', 'procurement@ntpc.co.in',         '+91-11-24360100', 'INR', 'ACTIVE', '07AAACN0291H1ZJ'),
('C005', 'Bharat Heavy Electricals Ltd',         'New Delhi', 'India',  45000000.00, 'NET45', 'purchase@bhel.in',               '+91-11-26001010', 'INR', 'ACTIVE', '07AAACB0472G1Z3'),
('C006', 'Indian Oil Corporation Ltd',           'Mumbai',    'India', 100000000.00, 'NET30', 'vendor@iocl.co.in',             '+91-22-26447616', 'INR', 'ACTIVE', '27AAACI1735M1ZN'),
('C007', 'Steel Authority of India Ltd',         'New Delhi', 'India',  40000000.00, 'NET45', 'materials@sail.in',              '+91-11-24367481', 'INR', 'ACTIVE', '07AAACS8731A1ZF'),
('C008', 'Tata Motors Ltd',                      'Mumbai',    'India',  55000000.00, 'NET30', 'procurement@tatamotors.com',     '+91-22-62407219', 'INR', 'ACTIVE', '27AAACT2727Q1ZA'),
('C009', 'Hindustan Petroleum Corp Ltd',         'Mumbai',    'India',  70000000.00, 'NET30', 'purchase@hpcl.in',               '+91-22-22614792', 'INR', 'ACTIVE', '27AAACH3449C1ZW'),
('C010', 'ONGC Ltd',                             'New Delhi', 'India',  90000000.00, 'NET60', 'vendor@ongc.co.in',              '+91-11-23301000', 'INR', 'ACTIVE', '07AAACO0196A1ZX'),
('C011', 'Voltas Ltd',                           'Mumbai',    'India',  32000000.00, 'NET45', 'procurement@voltas.com',         '+91-22-66656665', 'INR', 'ACTIVE', '27AAACV4981H1ZL'),
('C012', 'Bharat Electronics Ltd',               'Bengaluru', 'India',  48000000.00, 'NET45', 'purchase@bel-india.in',          '+91-80-25311234', 'INR', 'ACTIVE', '29AAACB0568A1ZA'),
('C013', 'Ashok Leyland Ltd',                    'Chennai',   'India',  42000000.00, 'NET30', 'vendor@ashokleyland.com',        '+91-44-28292100', 'INR', 'ACTIVE', '33AAACA5614G1ZD'),
('C014', 'TVS Motor Company Ltd',                'Chennai',   'India',  38000000.00, 'NET30', 'purchase@tvsmotor.com',          '+91-44-28338000', 'INR', 'ACTIVE', '33AAACT0934C1ZU'),
('C015', 'L&T Heavy Engineering',                'Mumbai',    'India',  85000000.00, 'NET60', 'procurement@larsentoubro.com',   '+91-22-67525656', 'INR', 'ACTIVE', '27AAACL0111L1ZA'),
('C016', 'Nuclear Power Corp of India Ltd',      'Mumbai',    'India',  65000000.00, 'NET60', 'vendor@npcil.co.in',             '+91-22-26001000', 'INR', 'ACTIVE', '27AAACN5643K1ZH'),
('C017', 'Adani Ports and SEZ Ltd',              'Ahmedabad', 'India',  55000000.00, 'NET45', 'purchase@adaniports.com',        '+91-79-25556628', 'INR', 'ACTIVE', '24AAACA9874L1ZN'),
('C018', 'BEML Ltd',                             'Bengaluru', 'India',  45000000.00, 'NET45', 'procurement@beml.co.in',         '+91-80-22963500', 'INR', 'ACTIVE', '29AAACB5432M1ZP'),
('C019', 'Hindustan Aeronautics Ltd',            'Bengaluru', 'India',  75000000.00, 'NET60', 'vendor@hal-india.co.in',         '+91-80-22320232', 'INR', 'ACTIVE', '29AAACH1234N1ZQ'),
('C020', 'Rail Vikas Nigam Ltd',                 'New Delhi', 'India',  60000000.00, 'NET60', 'purchase@rvnl.org',              '+91-11-41743000', 'INR', 'ACTIVE', '07AAACR4567P1ZR')
ON CONFLICT (customer_id) DO UPDATE SET credit_limit = EXCLUDED.credit_limit, name = EXCLUDED.name;

-- ── Sales Orders ─────────────────────────────────────────────────────────────────
INSERT INTO sales_orders (order_id, customer_id, material_id, qty, price, currency, status, delivery_date, plant) VALUES
('SO5001', 'C001', 'MAT011',   5.000, 2800000.00, 'INR', 'OPEN',      '2025-03-31', '1100'),
('SO5002', 'C002', 'MAT002', 100.000,   92000.00, 'INR', 'DELIVERED', '2024-12-20', '1000'),
('SO5003', 'C003', 'MAT012', 500.000,   18500.00, 'INR', 'OPEN',      '2025-03-28', '1200'),
('SO5004', 'C004', 'MAT015',  10.000,  185000.00, 'INR', 'DELIVERED', '2025-01-31', '1000'),
('SO5005', 'C005', 'MAT004',  15.000,  125000.00, 'INR', 'OPEN',      '2025-04-15', '1100'),
('SO5006', 'C006', 'MAT003', 1000.000,   8500.00, 'INR', 'OPEN',      '2025-03-15', '1000'),
('SO5007', 'C007', 'MAT005', 500.000,    4200.00, 'INR', 'DELIVERED', '2024-12-10', '1100'),
('SO5008', 'C008', 'MAT001',   8.000,  185000.00, 'INR', 'OPEN',      '2025-04-15', '1000'),
('SO5009', 'C009', 'MAT009',  30.000,   42000.00, 'INR', 'OPEN',      '2025-03-20', '1000'),
('SO5010', 'C010', 'MAT006',  20.000,   68000.00, 'INR', 'OPEN',      '2025-05-30', '1100'),
('SO5011', 'C001', 'MAT009',  15.000,   42000.00, 'INR', 'IN_TRANSIT','2025-02-20', '1000'),
('SO5012', 'C003', 'MAT015',   5.000,  185000.00, 'INR', 'OPEN',      '2025-04-20', '1300'),
('SO5013', 'C012', 'MAT028',   8.000,  215000.00, 'INR', 'OPEN',      '2025-04-30', '1000'),
('SO5014', 'C015', 'MAT011',   3.000, 2800000.00, 'INR', 'OPEN',      '2025-05-31', '1100'),
('SO5015', 'C013', 'MAT020',  12.000,  145000.00, 'INR', 'OPEN',      '2025-04-10', '1000'),
('SO5016', 'C014', 'MAT022',   5.000,  320000.00, 'INR', 'OPEN',      '2025-04-25', '1100'),
('SO5017', 'C005', 'MAT025',  20.000,   68000.00, 'INR', 'OPEN',      '2025-05-15', '1000'),
('SO5018', 'C016', 'MAT028',   6.000,  215000.00, 'INR', 'ON_HOLD',   '2025-06-30', '1000'),
('SO5019', 'C019', 'MAT011',   2.000, 2800000.00, 'INR', 'OPEN',      '2025-07-31', '1100'),
('SO5020', 'C018', 'MAT022',   8.000,  320000.00, 'INR', 'OPEN',      '2025-05-20', '1100'),
('SO5021', 'C008', 'MAT020',  15.000,  145000.00, 'INR', 'OPEN',      '2025-04-30', '1000'),
('SO5022', 'C002', 'MAT015',   8.000,  185000.00, 'INR', 'IN_TRANSIT','2025-03-15', '1300'),
('SO5023', 'C020', 'MAT011',   4.000, 2800000.00, 'INR', 'OPEN',      '2025-06-15', '1100'),
('SO5024', 'C017', 'MAT009',  50.000,   42000.00, 'INR', 'OPEN',      '2025-04-30', '1000'),
('SO5025', 'C004', 'MAT028',  10.000,  215000.00, 'INR', 'OPEN',      '2025-05-31', '1000'),
('SO5026', 'C011', 'MAT020',   6.000,  145000.00, 'INR', 'CANCELLED', '2025-02-28', '1000'),
('SO5027', 'C013', 'MAT004',  10.000,  125000.00, 'INR', 'DELIVERED', '2025-01-20', '1100'),
('SO5028', 'C003', 'MAT009',  40.000,   42000.00, 'INR', 'OPEN',      '2025-05-15', '1000'),
('SO5029', 'C006', 'MAT035',  30.000,   24000.00, 'INR', 'OPEN',      '2025-05-31', '1100'),
('SO5030', 'C007', 'MAT004',  12.000,  125000.00, 'INR', 'OPEN',      '2025-06-30', '1100')
ON CONFLICT (order_id) DO UPDATE SET status = EXCLUDED.status;

-- ── Deliveries ──────────────────────────────────────────────────────────────────
INSERT INTO deliveries (delivery_id, sales_order_id, status, ship_date, carrier, tracking_no) VALUES
('DEL6001', 'SO5002', 'DELIVERED',  '2024-12-18', 'Blue Dart Express Ltd',    'BD20241218001'),
('DEL6002', 'SO5004', 'DELIVERED',  '2025-01-28', 'DTDC Courier & Cargo',     'DTDC20250128055'),
('DEL6003', 'SO5007', 'DELIVERED',  '2024-12-08', 'FedEx India Pvt Ltd',      'FX20241208999'),
('DEL6004', 'SO5011', 'IN_TRANSIT', '2025-02-15', 'Gati KWE Pvt Ltd',         'GATI20250215112'),
('DEL6005', 'SO5022', 'IN_TRANSIT', '2025-03-10', 'Safexpress Pvt Ltd',       'SFX20250310034'),
('DEL6006', 'SO5027', 'DELIVERED',  '2025-01-18', 'TCI Express Ltd',          'TCI20250118076'),
('DEL6007', 'SO5001', 'PENDING',    NULL,          'Blue Dart Express Ltd',    NULL),
('DEL6008', 'SO5003', 'PENDING',    NULL,          'VRL Logistics Ltd',        NULL),
('DEL6009', 'SO5008', 'PENDING',    NULL,          'DHL Express India',        NULL),
('DEL6010', 'SO5014', 'PENDING',    NULL,          'Mahindra Logistics Ltd',   NULL)
ON CONFLICT (delivery_id) DO UPDATE SET status = EXCLUDED.status;

-- ── Employees ───────────────────────────────────────────────────────────────────
-- Level 7-8 leaders (no manager dependency)
INSERT INTO employees (emp_id, name, department, position, grade, join_date, manager_id, email, phone, status) VALUES
('EMP001', 'Rajesh Kumar',         'IT',         'VP Engineering',        'L7', '2015-06-01', NULL,    'rajesh.kumar@bpil.co.in',         '+91-9876543210', 'ACTIVE'),
('EMP010', 'Priya Sharma',         'HR',         'Director HR',           'L7', '2014-03-15', NULL,    'priya.sharma@bpil.co.in',         '+91-9876543220', 'ACTIVE'),
('EMP020', 'Suresh Iyer',          'Finance',    'CFO',                   'L8', '2012-01-10', NULL,    'suresh.iyer@bpil.co.in',          '+91-9876543230', 'ACTIVE'),
('EMP030', 'Anita Desai',          'Sales',      'VP Sales',              'L7', '2016-08-01', NULL,    'anita.desai@bpil.co.in',          '+91-9876543240', 'ACTIVE'),
('EMP040', 'Vikram Singh',         'Production', 'Plant Director',        'L7', '2013-05-20', NULL,    'vikram.singh@bpil.co.in',         '+91-9876543250', 'ACTIVE'),
('EMP047', 'Alok Chatterjee',      'SCM',        'Head Supply Chain',     'L7', '2014-09-01', NULL,    'alok.chatterjee@bpil.co.in',      '+91-9876543270', 'ACTIVE'),
('EMP050', 'Nitin Bhatt',          'R&D',        'R&D Director',          'L7', '2013-07-01', NULL,    'nitin.bhatt@bpil.co.in',          '+91-9876543260', 'ACTIVE')
ON CONFLICT (emp_id) DO UPDATE SET name = EXCLUDED.name;

-- Level 4-6 managers and seniors
INSERT INTO employees (emp_id, name, department, position, grade, join_date, manager_id, email, phone, status) VALUES
('EMP002', 'Meera Nair',           'IT',         'Senior Software Dev',   'L4', '2018-09-15', 'EMP001','meera.nair@bpil.co.in',           '+91-9876543211', 'ACTIVE'),
('EMP003', 'Arun Patel',           'IT',         'DevOps Engineer',       'L3', '2020-03-01', 'EMP001','arun.patel@bpil.co.in',           '+91-9876543212', 'ACTIVE'),
('EMP004', 'Kavya Reddy',          'IT',         'Data Analyst',          'L3', '2021-07-12', 'EMP001','kavya.reddy@bpil.co.in',          '+91-9876543213', 'ACTIVE'),
('EMP011', 'Ramesh Gupta',         'HR',         'HR Business Partner',   'L4', '2017-11-20', 'EMP010','ramesh.gupta@bpil.co.in',         '+91-9876543221', 'ACTIVE'),
('EMP012', 'Sunita Joshi',         'HR',         'Talent Acquisition Lead','L4','2019-02-14', 'EMP010','sunita.joshi@bpil.co.in',         '+91-9876543222', 'ACTIVE'),
('EMP021', 'Deepak Mehta',         'Finance',    'Finance Manager',       'L5', '2016-04-01', 'EMP020','deepak.mehta@bpil.co.in',         '+91-9876543231', 'ACTIVE'),
('EMP022', 'Pooja Verma',          'Finance',    'Senior Accountant',     'L4', '2019-08-25', 'EMP020','pooja.verma@bpil.co.in',          '+91-9876543232', 'ACTIVE'),
('EMP031', 'Manoj Tiwari',         'Sales',      'Regional Sales Head',   'L5', '2017-06-10', 'EMP030','manoj.tiwari@bpil.co.in',         '+91-9876543241', 'ACTIVE'),
('EMP032', 'Sneha Kulkarni',       'Sales',      'Key Account Manager',   'L4', '2020-01-15', 'EMP030','sneha.kulkarni@bpil.co.in',       '+91-9876543242', 'ACTIVE'),
('EMP041', 'Ravi Shankar',         'Production', 'Production Manager',    'L5', '2015-09-01', 'EMP040','ravi.shankar@bpil.co.in',         '+91-9876543251', 'ACTIVE'),
('EMP042', 'Lata Rao',             'Production', 'QA Manager',            'L5', '2017-03-15', 'EMP040','lata.rao@bpil.co.in',             '+91-9876543252', 'ACTIVE'),
('EMP048', 'Rekha Gowda',          'SCM',        'Procurement Manager',   'L5', '2016-05-10', 'EMP047','rekha.gowda@bpil.co.in',          '+91-9876543271', 'ACTIVE'),
('EMP049', 'Varun Malhotra',       'SCM',        'Logistics Manager',     'L5', '2017-08-20', 'EMP047','varun.malhotra@bpil.co.in',       '+91-9876543272', 'ACTIVE'),
('EMP051', 'Geeta Pillai',         'R&D',        'Principal Research Eng','L5', '2016-05-20', 'EMP050','geeta.pillai@bpil.co.in',         '+91-9876543261', 'ACTIVE'),
('EMP052', 'Divya Krishnamurthy',  'R&D',        'Product Design Lead',   'L5', '2018-06-01', 'EMP050','divya.krishnamurthy@bpil.co.in',  '+91-9876543262', 'ACTIVE')
ON CONFLICT (emp_id) DO UPDATE SET name = EXCLUDED.name;

-- Level 2-3 individual contributors
INSERT INTO employees (emp_id, name, department, position, grade, join_date, manager_id, email, phone, status) VALUES
('EMP043', 'Sandeep Mishra',       'Production', 'Production Supervisor', 'L3', '2022-04-01', 'EMP041','sandeep.mishra@bpil.co.in',       '+91-9876543253', 'ACTIVE'),
('EMP044', 'Kavitha Venkatesan',   'Production', 'Quality Inspector',     'L2', '2023-06-15', 'EMP042','kavitha.v@bpil.co.in',             '+91-9876543254', 'ACTIVE'),
('EMP045', 'Harish Nambiar',       'Production', 'CNC Machine Operator',  'L2', '2023-09-01', 'EMP041','harish.nambiar@bpil.co.in',       '+91-9876543255', 'ACTIVE'),
('EMP046', 'Sujata Patil',         'Production', 'Production Supervisor', 'L3', '2021-11-15', 'EMP041','sujata.patil@bpil.co.in',         '+91-9876543256', 'ACTIVE'),
('EMP053', 'Kiran Reddy',          'R&D',        'Mechanical Designer',   'L4', '2020-09-15', 'EMP052','kiran.reddy.rd@bpil.co.in',       '+91-9876543263', 'ACTIVE'),
('EMP054', 'Prasad Naidu',         'IT',         'Senior DevOps Engineer','L4', '2019-11-01', 'EMP001','prasad.naidu@bpil.co.in',         '+91-9876543214', 'ACTIVE'),
('EMP055', 'Anjali Bhattacharya',  'IT',         'Business Analyst',      'L4', '2020-07-15', 'EMP001','anjali.b@bpil.co.in',             '+91-9876543215', 'ACTIVE'),
('EMP056', 'Rohan Dasgupta',       'Finance',    'Finance Analyst',       'L3', '2022-04-01', 'EMP021','rohan.dasgupta@bpil.co.in',       '+91-9876543233', 'ACTIVE'),
('EMP057', 'Shalini Choudhary',    'HR',         'HR Operations Specialist','L3','2021-12-01','EMP011','shalini.choudhary@bpil.co.in',    '+91-9876543223', 'ACTIVE'),
('EMP058', 'Tarun Agarwal',        'Sales',      'Sales Executive',       'L2', '2023-03-15', 'EMP031','tarun.agarwal@bpil.co.in',        '+91-9876543243', 'ACTIVE'),
('EMP059', 'Meghna Pillai',        'Sales',      'Product Specialist',    'L3', '2022-08-01', 'EMP031','meghna.pillai@bpil.co.in',        '+91-9876543244', 'ACTIVE'),
('EMP060', 'Ashwin Rao',           'Production', 'CNC Programmer',        'L3', '2022-02-01', 'EMP041','ashwin.rao@bpil.co.in',           '+91-9876543257', 'ACTIVE'),
('EMP061', 'Nandini Jain',         'IT',         'UI/UX Designer',        'L3', '2021-10-15', 'EMP001','nandini.jain@bpil.co.in',         '+91-9876543216', 'ACTIVE'),
('EMP062', 'Arjun Chakraborty',    'R&D',        'Test & Validation Eng', 'L3', '2023-01-10', 'EMP051','arjun.chakraborty@bpil.co.in',    '+91-9876543264', 'ACTIVE'),
('EMP063', 'Lakshmi Varma',        'Finance',    'Direct Taxation Spec',  'L4', '2019-07-20', 'EMP021','lakshmi.varma@bpil.co.in',        '+91-9876543234', 'ACTIVE'),
('EMP064', 'Vinod Kumar',          'Production', 'Maintenance Engineer',  'L3', '2020-12-01', 'EMP041','vinod.kumar@bpil.co.in',          '+91-9876543258', 'ACTIVE'),
('EMP065', 'Swati Pandey',         'SCM',        'Procurement Specialist','L3', '2021-08-20', 'EMP048','swati.pandey@bpil.co.in',         '+91-9876543273', 'ACTIVE'),
('EMP066', 'Kunal Saxena',         'SCM',        'Logistics Coordinator', 'L3', '2022-05-10', 'EMP049','kunal.saxena@bpil.co.in',         '+91-9876543274', 'ACTIVE')
ON CONFLICT (emp_id) DO UPDATE SET name = EXCLUDED.name;

-- ── Leave Balances (FY 2024-25) ─────────────────────────────────────────────────
INSERT INTO leave_balances (emp_id, fiscal_year, annual_entitled, annual_used, sick_entitled, sick_used, casual_entitled, casual_used) VALUES
('EMP001', 2025, 21,  6.0, 12, 0.0, 8, 1.0),
('EMP002', 2025, 21,  9.0, 12, 3.0, 8, 2.0),
('EMP003', 2025, 21,  4.0, 12, 1.0, 8, 1.0),
('EMP004', 2025, 21,  7.0, 12, 2.0, 8, 0.0),
('EMP010', 2025, 21,  5.0, 12, 1.0, 8, 2.0),
('EMP011', 2025, 21,  8.0, 12, 2.0, 8, 3.0),
('EMP012', 2025, 21, 12.0, 12, 4.0, 8, 3.0),
('EMP020', 2025, 21,  3.0, 12, 0.0, 8, 1.0),
('EMP021', 2025, 21,  7.0, 12, 1.0, 8, 2.0),
('EMP022', 2025, 21,  9.0, 12, 3.0, 8, 1.0),
('EMP030', 2025, 21,  6.0, 12, 0.0, 8, 2.0),
('EMP031', 2025, 21, 11.0, 12, 3.0, 8, 2.0),
('EMP032', 2025, 21,  5.0, 12, 1.0, 8, 0.0),
('EMP040', 2025, 21,  4.0, 12, 1.0, 8, 1.0),
('EMP041', 2025, 21,  7.0, 12, 2.0, 8, 1.0),
('EMP042', 2025, 21,  3.0, 12, 0.0, 8, 1.0),
('EMP043', 2025, 21, 10.0, 12, 4.0, 8, 2.0),
('EMP044', 2025, 21,  6.0, 12, 2.0, 8, 1.0),
('EMP045', 2025, 21,  5.0, 12, 1.0, 8, 0.0),
('EMP046', 2025, 21,  8.0, 12, 3.0, 8, 2.0),
('EMP047', 2025, 21,  5.0, 12, 0.0, 8, 1.0),
('EMP048', 2025, 21,  7.0, 12, 2.0, 8, 1.0),
('EMP049', 2025, 21,  6.0, 12, 1.0, 8, 2.0),
('EMP050', 2025, 21,  8.0, 12, 1.0, 8, 2.0),
('EMP051', 2025, 21, 11.0, 12, 4.0, 8, 2.0),
('EMP052', 2025, 21,  4.0, 12, 0.0, 8, 1.0),
('EMP053', 2025, 21,  7.0, 12, 2.0, 8, 0.0),
('EMP054', 2025, 21,  5.0, 12, 1.0, 8, 1.0),
('EMP055', 2025, 21,  9.0, 12, 3.0, 8, 2.0),
('EMP056', 2025, 21,  4.0, 12, 1.0, 8, 0.0),
('EMP057', 2025, 21, 13.0, 12, 5.0, 8, 3.0),
('EMP058', 2025, 21,  3.0, 12, 0.0, 8, 0.0),
('EMP059', 2025, 21,  6.0, 12, 1.0, 8, 1.0),
('EMP060', 2025, 21,  5.0, 12, 2.0, 8, 1.0),
('EMP061', 2025, 21,  7.0, 12, 1.0, 8, 2.0),
('EMP062', 2025, 21,  4.0, 12, 0.0, 8, 0.0),
('EMP063', 2025, 21,  8.0, 12, 2.0, 8, 1.0),
('EMP064', 2025, 21,  6.0, 12, 3.0, 8, 1.0),
('EMP065', 2025, 21,  5.0, 12, 1.0, 8, 0.0),
('EMP066', 2025, 21,  4.0, 12, 0.0, 8, 1.0)
ON CONFLICT (emp_id, fiscal_year) DO UPDATE SET annual_used = EXCLUDED.annual_used, sick_used = EXCLUDED.sick_used;

-- ── Payroll (January 2025 — latest processed month) ──────────────────────────────
INSERT INTO payroll (emp_id, pay_month, pay_year, basic, hra, allowances, deductions, net, currency, processed_on) VALUES
('EMP001', 1, 2025, 290000.00, 116000.00, 43500.00,  61000.00,  388500.00, 'INR', '2025-01-31'),
('EMP002', 1, 2025, 152000.00,  60800.00, 22800.00,  30400.00,  205200.00, 'INR', '2025-01-31'),
('EMP003', 1, 2025, 115000.00,  46000.00, 17250.00,  23000.00,  155250.00, 'INR', '2025-01-31'),
('EMP004', 1, 2025, 110000.00,  44000.00, 16500.00,  22000.00,  148500.00, 'INR', '2025-01-31'),
('EMP010', 1, 2025, 268000.00, 107200.00, 40200.00,  55500.00,  359900.00, 'INR', '2025-01-31'),
('EMP011', 1, 2025, 156000.00,  62400.00, 23400.00,  31200.00,  210600.00, 'INR', '2025-01-31'),
('EMP012', 1, 2025, 152000.00,  60800.00, 22800.00,  30400.00,  205200.00, 'INR', '2025-01-31'),
('EMP020', 1, 2025, 465000.00, 186000.00, 69750.00,  98000.00,  622750.00, 'INR', '2025-01-31'),
('EMP021', 1, 2025, 205000.00,  82000.00, 30750.00,  41000.00,  276750.00, 'INR', '2025-01-31'),
('EMP022', 1, 2025, 146000.00,  58400.00, 21900.00,  29200.00,  197100.00, 'INR', '2025-01-31'),
('EMP030', 1, 2025, 278000.00, 111200.00, 41700.00,  57800.00,  373100.00, 'INR', '2025-01-31'),
('EMP031', 1, 2025, 208000.00,  83200.00, 31200.00,  41600.00,  280800.00, 'INR', '2025-01-31'),
('EMP032', 1, 2025, 162000.00,  64800.00, 24300.00,  32400.00,  218700.00, 'INR', '2025-01-31'),
('EMP040', 1, 2025, 272000.00, 108800.00, 40800.00,  56500.00,  365100.00, 'INR', '2025-01-31'),
('EMP041', 1, 2025, 198000.00,  79200.00, 29700.00,  39600.00,  267300.00, 'INR', '2025-01-31'),
('EMP042', 1, 2025, 195000.00,  78000.00, 29250.00,  39000.00,  263250.00, 'INR', '2025-01-31'),
('EMP043', 1, 2025, 118000.00,  47200.00, 17700.00,  23600.00,  159300.00, 'INR', '2025-01-31'),
('EMP044', 1, 2025,  72000.00,  28800.00, 10800.00,  14400.00,   97200.00, 'INR', '2025-01-31'),
('EMP045', 1, 2025,  68000.00,  27200.00, 10200.00,  13600.00,   91800.00, 'INR', '2025-01-31'),
('EMP046', 1, 2025, 120000.00,  48000.00, 18000.00,  24000.00,  162000.00, 'INR', '2025-01-31'),
('EMP047', 1, 2025, 268000.00, 107200.00, 40200.00,  55500.00,  359900.00, 'INR', '2025-01-31'),
('EMP048', 1, 2025, 198000.00,  79200.00, 29700.00,  39600.00,  267300.00, 'INR', '2025-01-31'),
('EMP049', 1, 2025, 195000.00,  78000.00, 29250.00,  39000.00,  263250.00, 'INR', '2025-01-31'),
('EMP050', 1, 2025, 272000.00, 108800.00, 40800.00,  56500.00,  365100.00, 'INR', '2025-01-31'),
('EMP051', 1, 2025, 208000.00,  83200.00, 31200.00,  41600.00,  280800.00, 'INR', '2025-01-31'),
('EMP052', 1, 2025, 205000.00,  82000.00, 30750.00,  41000.00,  276750.00, 'INR', '2025-01-31'),
('EMP053', 1, 2025, 152000.00,  60800.00, 22800.00,  30400.00,  205200.00, 'INR', '2025-01-31'),
('EMP054', 1, 2025, 155000.00,  62000.00, 23250.00,  31000.00,  209250.00, 'INR', '2025-01-31'),
('EMP055', 1, 2025, 150000.00,  60000.00, 22500.00,  30000.00,  202500.00, 'INR', '2025-01-31'),
('EMP056', 1, 2025, 112000.00,  44800.00, 16800.00,  22400.00,  151200.00, 'INR', '2025-01-31'),
('EMP057', 1, 2025, 118000.00,  47200.00, 17700.00,  23600.00,  159300.00, 'INR', '2025-01-31'),
('EMP058', 1, 2025,  72000.00,  28800.00, 10800.00,  14400.00,   97200.00, 'INR', '2025-01-31'),
('EMP059', 1, 2025, 118000.00,  47200.00, 17700.00,  23600.00,  159300.00, 'INR', '2025-01-31'),
('EMP060', 1, 2025, 120000.00,  48000.00, 18000.00,  24000.00,  162000.00, 'INR', '2025-01-31'),
('EMP061', 1, 2025, 118000.00,  47200.00, 17700.00,  23600.00,  159300.00, 'INR', '2025-01-31'),
('EMP062', 1, 2025, 110000.00,  44000.00, 16500.00,  22000.00,  148500.00, 'INR', '2025-01-31'),
('EMP063', 1, 2025, 152000.00,  60800.00, 22800.00,  30400.00,  205200.00, 'INR', '2025-01-31'),
('EMP064', 1, 2025, 118000.00,  47200.00, 17700.00,  23600.00,  159300.00, 'INR', '2025-01-31'),
('EMP065', 1, 2025, 115000.00,  46000.00, 17250.00,  23000.00,  155250.00, 'INR', '2025-01-31'),
('EMP066', 1, 2025, 112000.00,  44800.00, 16800.00,  22400.00,  151200.00, 'INR', '2025-01-31')
ON CONFLICT (emp_id, pay_month, pay_year) DO UPDATE SET net = EXCLUDED.net;

-- ── Work Centers ─────────────────────────────────────────────────────────────────
INSERT INTO work_centers (wc_id, name, plant, capacity, capacity_unit, status) VALUES
('WC001', 'CNC Turning Centre DMG CTX 500',    '1100', 16.00, 'HR', 'ACTIVE'),
('WC002', 'CNC Milling Centre Mazak VTC 530',  '1100', 16.00, 'HR', 'ACTIVE'),
('WC003', 'Assembly Line A — Automation',      '1100', 24.00, 'HR', 'ACTIVE'),
('WC004', 'MIG/TIG Welding Station',           '1100', 16.00, 'HR', 'ACTIVE'),
('WC005', 'Paint Shop Automated Spray',        '1100', 20.00, 'HR', 'MAINTENANCE'),
('WC006', 'Robotic Assembly Cell FANUC',       '1100', 24.00, 'HR', 'ACTIVE'),
('WC007', 'Electrical Testing & QC Lab',       '1000', 16.00, 'HR', 'ACTIVE'),
('WC008', 'Packaging & Despatch',              '1200', 20.00, 'HR', 'ACTIVE'),
('WC009', 'Surface Grinding Machine',          '1100', 16.00, 'HR', 'ACTIVE'),
('WC010', 'CMM Inspection — Zeiss Contura',    '1100', 12.00, 'HR', 'ACTIVE'),
('WC011', 'Heat Treatment Furnace 1000C',      '1100', 20.00, 'HR', 'ACTIVE'),
('WC012', 'Assembly Test Bench Hydraulic',     '1100', 16.00, 'HR', 'ACTIVE')
ON CONFLICT (wc_id) DO UPDATE SET status = EXCLUDED.status;

-- ── Production Orders ────────────────────────────────────────────────────────────
INSERT INTO production_orders (order_id, material_id, qty, unit, plant, work_center_id, status, planned_start, planned_end) VALUES
('PRD7001', 'MAT011',  3.000, 'EA', '1100', 'WC006', 'IN_PROCESS',           '2025-01-15', '2025-03-31'),
('PRD7002', 'MAT009', 25.000, 'EA', '1000', 'WC007', 'RELEASED',             '2025-02-01', '2025-02-28'),
('PRD7003', 'MAT015',  5.000, 'EA', '1000', 'WC007', 'COMPLETED',            '2025-01-10', '2025-01-25'),
('PRD7004', 'MAT012',200.000, 'EA', '1200', 'WC008', 'COMPLETED',            '2025-01-10', '2025-01-31'),
('PRD7005', 'MAT001',  6.000, 'EA', '1000', 'WC007', 'CREATED',              '2025-03-01', '2025-04-15'),
('PRD7006', 'MAT002', 80.000, 'EA', '1000', 'WC007', 'TECHNICALLY_COMPLETED','2024-12-01', '2024-12-31'),
('PRD7007', 'MAT009', 10.000, 'EA', '1000', 'WC007', 'RELEASED',             '2025-02-05', '2025-02-25'),
('PRD7008', 'MAT020',  8.000, 'EA', '1000', 'WC007', 'IN_PROCESS',           '2025-02-15', '2025-03-20'),
('PRD7009', 'MAT022',  4.000, 'EA', '1100', 'WC003', 'CREATED',              '2025-03-15', '2025-05-15'),
('PRD7010', 'MAT016',100.000, 'EA', '1100', 'WC001', 'IN_PROCESS',           '2025-02-01', '2025-03-15'),
('PRD7011', 'MAT025', 15.000, 'EA', '1000', 'WC007', 'RELEASED',             '2025-02-20', '2025-03-20'),
('PRD7012', 'MAT009', 30.000, 'EA', '1000', 'WC007', 'CREATED',              '2025-03-20', '2025-04-20'),
('PRD7013', 'MAT021', 20.000, 'SET','1100', 'WC002', 'IN_PROCESS',           '2025-01-25', '2025-03-10'),
('PRD7014', 'MAT011',  2.000, 'EA', '1100', 'WC006', 'CREATED',              '2025-04-01', '2025-06-30'),
('PRD7015', 'MAT028', 10.000, 'EA', '1000', 'WC007', 'RELEASED',             '2025-03-01', '2025-03-31')
ON CONFLICT (order_id) DO UPDATE SET status = EXCLUDED.status;

-- ── Bill of Materials ────────────────────────────────────────────────────────────
INSERT INTO bom (parent_material_id, component_id, qty, unit) VALUES
-- MAT011 — 6-Axis Industrial Robot
('MAT011', 'MAT005',  120.000, 'EA'),   -- MS Steel Sheets
('MAT011', 'MAT008',   24.000, 'EA'),   -- SKF Bearings 6205
('MAT011', 'MAT006',    2.000, 'EA'),   -- Hydraulic Pumps
('MAT011', 'MAT003',   50.000, 'ROL'),  -- Copper Cables
('MAT011', 'MAT036',    8.000, 'EA'),   -- Ground Shafts
('MAT011', 'MAT031',   12.000, 'EA'),   -- Bearings 6308
-- MAT020 — Variable Frequency Drive 15kW
('MAT020', 'MAT027',    1.000, 'EA'),   -- Servo Motor 750W
('MAT020', 'MAT029',    1.000, 'EA'),   -- Ethernet Switch
('MAT020', 'MAT026',    1.000, 'EA'),   -- Aluminium Housing
('MAT020', 'MAT037',    3.000, 'EA'),   -- Contactors
-- MAT022 — Industrial Gearbox
('MAT022', 'MAT021',    1.000, 'SET'),  -- Helical Gear Set
('MAT022', 'MAT008',    8.000, 'EA'),   -- Bearings
('MAT022', 'MAT032',   20.000, 'LT'),   -- Hydraulic Oil fill
('MAT022', 'MAT023',   10.000, 'PKT'),  -- O-Rings
-- MAT009 — Control Panel MCC
('MAT009', 'MAT008',    4.000, 'EA'),   -- Bearings
('MAT009', 'MAT003',   10.000, 'ROL'),  -- Copper Cables
('MAT009', 'MAT037',    6.000, 'EA'),   -- Contactors
-- MAT001 — Server Rack 42U
('MAT001', 'MAT014',   20.000, 'EA'),   -- Aluminium Profiles
('MAT001', 'MAT003',   15.000, 'ROL'),  -- Copper Cables
('MAT001', 'MAT040',    4.000, 'EA'),   -- Cable Trays
-- MAT015 — PLC Siemens S7-1500
('MAT015', 'MAT008',    6.000, 'EA'),   -- Bearings
('MAT015', 'MAT003',    8.000, 'ROL'),  -- Cables
-- MAT016 — CNC Turned Shaft
('MAT016', 'MAT036',    1.000, 'EA'),   -- EN8 Ground Shaft raw
('MAT016', 'MAT030',    5.000, 'EA');   -- Carbide Inserts consumed

-- ── ABAP Programs ────────────────────────────────────────────────────────────────
INSERT INTO abap_programs (program_name, description, program_type, package, created_by, created_on, line_count, status, last_changed) VALUES
('ZREP_VENDOR_LIST',          'Vendor Master List with Payment Analysis',       'REPORT', 'ZFICO',   'ABAP_DEV',  '2022-03-10',  485, 'ACTIVE', '2024-11-15'),
('ZREP_INVOICE_AGING',        'Invoice Aging & Overdue Alert Report',           'REPORT', 'ZFICO',   'ABAP_DEV',  '2022-06-20',  672, 'ACTIVE', '2025-01-15'),
('ZBDC_VENDOR_UPLOAD',        'Vendor Master BDC Batch Upload Program',         'REPORT', 'ZFICO',   'BASIS_ADM', '2021-09-05',  234, 'ACTIVE', '2023-12-20'),
('ZREP_STOCK_VALUATION',      'Stock Valuation — Moving Average Price Report',  'REPORT', 'ZMM',     'ABAP_DEV',  '2023-01-15',  810, 'ACTIVE', '2025-02-01'),
('ZREP_PO_STATUS',            'Purchase Order Status & GR Tracking Report',     'REPORT', 'ZMM',     'ABAP_DEV',  '2022-11-10',  523, 'ACTIVE', '2024-12-10'),
('ZREP_SALES_ANALYSIS',       'Sales Order Analysis — Region & Product Mix',    'REPORT', 'ZSD',     'ABAP_DEV',  '2023-04-20',  948, 'ACTIVE', '2025-01-20'),
('ZREP_HR_HEADCOUNT',         'HR Headcount & Department Attrition Report',     'REPORT', 'ZHR',     'ABAP_DEV',  '2022-08-01',  612, 'ACTIVE', '2024-09-20'),
('ZREP_PAYROLL_SUMMARY',      'Monthly Payroll Summary with PF/ESI Details',   'REPORT', 'ZHR',     'HR_ADMIN',  '2021-12-15',  389, 'ACTIVE', '2025-02-01'),
('ZENH_LEAVE_WORKFLOW',       'Leave Approval Workflow Exit Enhancement',       'EXIT',   'ZHR',     'ABAP_DEV',  '2023-06-10',  245, 'ACTIVE', '2024-08-15'),
('ZREP_PROD_EFFICIENCY',      'Production Order Efficiency & OEE Dashboard',   'REPORT', 'ZPP',     'ABAP_DEV',  '2023-02-28',  734, 'ACTIVE', '2025-01-10'),
('ZFUNC_VALIDATE_GST',        'GST Number Format & Checksum Validation ABAP',  'FUGR',   'ZUTILS',  'ABAP_DEV',  '2023-07-01',  156, 'ACTIVE', '2024-11-10'),
('ZREP_ASSET_REGISTER',       'Fixed Asset Register — Depreciation Schedule',  'REPORT', 'ZFICO',   'ABAP_DEV',  '2022-04-15',  543, 'ACTIVE', '2024-07-20'),
('ZREP_GST_RECONCILIATION',   'GSTR-2A vs Purchase Ledger Reconciliation',     'REPORT', 'ZFICO',   'ABAP_DEV',  '2024-01-10',  892, 'ACTIVE', '2025-02-15'),
('ZREP_BANK_RECONCILIATION',  'Bank Statement Auto-Reconciliation Report',      'REPORT', 'ZFICO',   'ABAP_DEV',  '2023-10-05',  645, 'ACTIVE', '2025-01-05'),
('ZREP_PROD_ORDER_COCKPIT',   'Production Order Cockpit — Real-Time Status',   'REPORT', 'ZPP',     'ABAP_DEV',  '2024-03-15',  1120,'ACTIVE', '2025-02-20'),
('ZBDC_CUSTOMER_UPLOAD',      'Customer Master BDC Upload with Validation',    'REPORT', 'ZSD',     'BASIS_ADM', '2022-05-20',  312, 'ACTIVE', '2024-04-10'),
('ZENH_PO_APPROVAL',          'Purchase Order Multi-Level Approval Workflow',  'EXIT',   'ZMM',     'ABAP_DEV',  '2023-09-01',  478, 'ACTIVE', '2024-12-15'),
('ZREP_ASSET_DEPRECIATION',   'Asset Depreciation Run — WDV Method Report',    'REPORT', 'ZFICO',   'ABAP_DEV',  '2024-02-01',  567, 'ACTIVE', '2025-01-31'),
('ZREP_MATERIAL_VALUATION',   'Material Ledger Valuation Period-End Report',   'REPORT', 'ZMM',     'ABAP_DEV',  '2023-11-20',  742, 'ACTIVE', '2025-02-10'),
('ZREP_CUSTOMER_AGING',       'Customer Receivables Aging with DSO Analysis',  'REPORT', 'ZSD',     'ABAP_DEV',  '2023-08-15',  688, 'ACTIVE', '2025-01-25')
ON CONFLICT (program_name) DO UPDATE SET line_count = EXCLUDED.line_count;

-- ── Function Modules ─────────────────────────────────────────────────────────────
INSERT INTO function_modules (fm_name, description, function_group, package, parameters, created_by, status) VALUES
('Z_GET_VENDOR_MASTER',       'Get Vendor Master Data by Vendor ID',           'ZFGRP_FI', 'ZFICO',  'IV_VENDOR_ID, ET_VENDOR_DATA, EV_STATUS',    'ABAP_DEV', 'ACTIVE'),
('Z_VALIDATE_GST_NUMBER',     'Validate GST Number Format and State Code',     'ZFGRP_UT', 'ZUTILS', 'IV_GST_NO, EV_VALID, EV_STATE, EV_PAN',      'ABAP_DEV', 'ACTIVE'),
('Z_CALC_LEAVE_BALANCE',      'Calculate Employee Leave Balance by Period',    'ZFGRP_HR', 'ZHR',   'IV_EMP_ID, IV_FISCAL_YEAR, ET_LEAVE_BAL',    'ABAP_DEV', 'ACTIVE'),
('Z_GET_STOCK_OVERVIEW',      'Get Material Stock by Plant with Reorder Flag', 'ZFGRP_MM', 'ZMM',   'IV_MATNR, IV_WERKS, ES_STOCK, EV_REORDER',  'ABAP_DEV', 'ACTIVE'),
('Z_POST_INVOICE',            'Post Vendor Invoice to FI with Validation',     'ZFGRP_FI', 'ZFICO', 'IS_INVOICE_HDR, IT_ITEMS, EV_BELNR, ET_MSG', 'ABAP_DEV', 'ACTIVE'),
('Z_CREATE_SALES_ORDER',      'Create Sales Order Programmatically VA01',      'ZFGRP_SD', 'ZSD',   'IS_ORDER_HDR, IT_ITEMS, EV_VBELN, ET_MSG',   'ABAP_DEV', 'ACTIVE'),
('Z_SEND_EMAIL_NOTIF',        'Send Email Notification via SCOT Configuration','ZFGRP_UT', 'ZUTILS','IV_RECIPIENT, IV_SUBJECT, IV_BODY, EV_SENT',  'BASIS_ADM','ACTIVE'),
('Z_GET_PROD_ORDER_STATUS',   'Get Production Order Status and Components',    'ZFGRP_PP', 'ZPP',   'IV_ORDER_ID, ES_HEADER, ET_COMPONENTS',       'ABAP_DEV', 'ACTIVE'),
('Z_CALC_DEPRECIATION',       'Calculate Asset Depreciation WDV Method',       'ZFGRP_FI', 'ZFICO', 'IV_ASSET_NO, IV_PERIOD, EV_DEP_AMT',         'ABAP_DEV', 'ACTIVE'),
('Z_VALIDATE_MATERIAL',       'Validate Material Master Consistency',          'ZFGRP_MM', 'ZMM',   'IV_MATNR, EV_VALID, ET_ERRORS',              'ABAP_DEV', 'ACTIVE')
ON CONFLICT (fm_name) DO UPDATE SET description = EXCLUDED.description;

-- ── Transport Requests ────────────────────────────────────────────────────────────
INSERT INTO transport_requests (tr_id, description, tr_type, status, owner, created_on, released_on, target, objects) VALUES
('DEVK900123', 'FI Invoice Aging Report — Overdue Alert Feature',         'Workbench',    'RELEASED',   'ABAP_DEV',  '2024-11-01', '2024-11-20', 'QUALITY',     'ZREP_INVOICE_AGING, Z_POST_INVOICE'),
('DEVK900124', 'HR Leave Workflow — Carry Forward Bugfix',                'Workbench',    'MODIFIABLE', 'ABAP_DEV',  '2024-12-05', NULL,         'QUALITY',     'ZENH_LEAVE_WORKFLOW'),
('DEVK900125', 'GST Validation — PAN Check & State Code Enhancement',     'Workbench',    'RELEASED',   'ABAP_DEV',  '2024-10-15', '2024-11-05', 'PRODUCTION',  'ZFUNC_VALIDATE_GST, Z_VALIDATE_GST_NUMBER'),
('DEVK900126', 'Stock Valuation Report — Performance Optimization',       'Workbench',    'MODIFIABLE', 'ABAP_DEV',  '2025-01-05', NULL,         'QUALITY',     'ZREP_STOCK_VALUATION'),
('DEVK900127', 'Sales Analysis Dashboard v2 — Region Drill-Down',         'Workbench',    'RELEASED',   'ABAP_DEV',  '2024-09-20', '2024-10-15', 'PRODUCTION',  'ZREP_SALES_ANALYSIS'),
('DEVK900128', 'Payroll Summary — PF Wage Ceiling Update FY 2024-25',    'Workbench',    'RELEASED',   'HR_ADMIN',  '2025-01-10', '2025-01-25', 'QUALITY',     'ZREP_PAYROLL_SUMMARY'),
('DEVK900129', 'GST Reconciliation New Report GSTR-2A',                   'Workbench',    'MODIFIABLE', 'ABAP_DEV',  '2025-02-01', NULL,         'QUALITY',     'ZREP_GST_RECONCILIATION'),
('DEVK900130', 'Bank Reconciliation — Auto-Match Algorithm v2',           'Workbench',    'RELEASED',   'ABAP_DEV',  '2024-12-10', '2025-01-10', 'PRODUCTION',  'ZREP_BANK_RECONCILIATION'),
('DEVK900131', 'Production Order Cockpit — OEE Dashboard',                'Workbench',    'MODIFIABLE', 'ABAP_DEV',  '2025-02-10', NULL,         'QUALITY',     'ZREP_PROD_ORDER_COCKPIT, Z_GET_PROD_ORDER_STATUS'),
('DEVK900132', 'PO Multi-Level Approval Workflow Configuration',          'Customizing',  'RELEASED',   'ABAP_DEV',  '2024-08-20', '2024-09-15', 'PRODUCTION',  'ZENH_PO_APPROVAL'),
('DEVK900133', 'Customer Master BDC Upload — GST Validation Bugfix',      'Workbench',    'MODIFIABLE', 'BASIS_ADM', '2025-01-20', NULL,         'QUALITY',     'ZBDC_CUSTOMER_UPLOAD'),
('DEVK900134', 'Material Ledger Valuation — Period-End Closing Report',   'Workbench',    'RELEASED',   'ABAP_DEV',  '2024-11-15', '2024-12-20', 'PRODUCTION',  'ZREP_MATERIAL_VALUATION')
ON CONFLICT (tr_id) DO UPDATE SET status = EXCLUDED.status;

-- ============================================================
-- Alembic Real Estate — "Parivartan" Project Seed Data
-- Projects: Cloud Forest, Park Crescent
-- ============================================================

-- ── RE Customers ─────────────────────────────────────────────────────────────────
INSERT INTO re_customers (customer_id, name, pan_number, aadhaar, dob, phone, email, address, city, state, project, unit_number, tower, floor, area_sqft, area_sqm, sale_value, gst_number, co_applicant, booking_date) VALUES
('ALEC001', 'Rahul Sharma',          'ABCPS1234D', '9876-5432-1098', '1985-06-15', '9876543210', 'rahul.sharma@email.com',    '12 Anand Nagar, Sector 7',  'Ahmedabad', 'Gujarat', 'CLOUD_FOREST',  'T1-304', 'T1', '3', 1250.00, 116.13, 6500000.00, NULL,               'Priya Sharma',   '2024-04-10'),
('ALEC002', 'Priya Nair',            'XYZPN9876A', '8765-4321-0987', '1990-02-20', '9123456789', 'priya.nair@email.com',      '45 Marine Lines, Colaba',   'Mumbai',    'Maharashtra', 'CLOUD_FOREST', 'T2-201', 'T2', '2', 980.00,  91.04,  4800000.00, NULL,               'Anil Nair',      '2024-05-18'),
('ALEC003', 'Vikram Patel',          'DEFVP4567H', '7654-3210-9876', '1978-11-03', '9988776655', 'vikram.patel@email.com',    '78 Satellite Road',         'Ahmedabad', 'Gujarat', 'PARK_CRESCENT', 'PC-1102','PC', '11',1100.00, 102.19, 5500000.00, NULL,               NULL,             '2024-06-25'),
('ALEC004', 'Sunita Mehta Corp',     'GHIJK5678B', '6543-2109-8765', '1975-08-12', '9900112233', 'sunita@mehtacorp.in',       '34 GIDC Industrial Estate', 'Surat',     'Gujarat', 'CLOUD_FOREST',  'T1-506', 'T1', '5', 1400.00, 130.06, 7200000.00, '24GHIJK5678B1ZQ', NULL,             '2024-07-01'),
('ALEC005', 'Rajesh Kumar',          'LMNOP2345C', '5432-1098-7654', '1982-03-28', '9871234560', 'rajesh.kumar@email.com',    '89 Navrangpura',             'Ahmedabad', 'Gujarat', 'PARK_CRESCENT', 'PC-0802','PC', '8', 890.00,  82.68,  4200000.00, NULL,               'Anita Kumar',    '2024-08-15')
ON CONFLICT (customer_id) DO UPDATE SET name = EXCLUDED.name;

-- ── RE Milestones — ALEC001 / T1-304 ────────────────────────────────────────────
INSERT INTO re_milestones (customer_id, unit_number, milestone_code, description, billing_doc_no, basic_amt, cgst_amt, sgst_amt, tds_amt, basic_collected, cgst_collected, sgst_collected, tds_collected, status, billing_date) VALUES
-- M01 Booking — Fully Collected
('ALEC001','T1-304','M01','Booking Amount',        '9000010001', 200000.00,  18000.00,  18000.00, 0.00,  200000.00, 18000.00, 18000.00, 0.00, 'COLLECTED', '2024-04-10'),
-- M02 Foundation — Fully Collected
('ALEC001','T1-304','M02','Foundation Completion',  '9000010002', 500000.00,  45000.00,  45000.00, 0.00,  500000.00, 45000.00, 45000.00, 0.00, 'COLLECTED', '2024-07-15'),
-- M03 Plinth — Partially Collected (₹350,000 basic outstanding)
('ALEC001','T1-304','M03','Plinth Level',           '9000010003', 700000.00,  63000.00,  63000.00, 0.00,  350000.00, 20000.00,  20000.00, 0.00, 'PARTIAL',   '2024-10-20'),
-- M04 Slab Level 3 — Pending
('ALEC001','T1-304','M04','Slab Level 3',           '9000010004', 800000.00,  72000.00,  72000.00, 0.00,       0.00,     0.00,      0.00, 0.00, 'PENDING',   '2025-01-15'),
-- M05 Possession — Pending
('ALEC001','T1-304','M05','Possession',             '9000010005',1200000.00, 108000.00, 108000.00, 0.00,       0.00,     0.00,      0.00, 0.00, 'PENDING',   NULL)
ON CONFLICT (customer_id, unit_number, milestone_code) DO UPDATE SET status = EXCLUDED.status, basic_collected = EXCLUDED.basic_collected;

-- ── RE Milestones — ALEC002 / T2-201 ────────────────────────────────────────────
INSERT INTO re_milestones (customer_id, unit_number, milestone_code, description, billing_doc_no, basic_amt, cgst_amt, sgst_amt, tds_amt, basic_collected, cgst_collected, sgst_collected, tds_collected, status, billing_date) VALUES
('ALEC002','T2-201','M01','Booking Amount',        '9000020001', 144000.00, 12960.00, 12960.00, 0.00, 144000.00, 12960.00, 12960.00, 0.00, 'COLLECTED', '2024-05-18'),
('ALEC002','T2-201','M02','Foundation Completion', '9000020002', 384000.00, 34560.00, 34560.00, 0.00,  57600.00,  5184.00,  5184.00, 0.00, 'PARTIAL',   '2024-09-10'),
('ALEC002','T2-201','M03','Plinth Level',          NULL,         480000.00, 43200.00, 43200.00, 0.00,      0.00,     0.00,     0.00, 0.00, 'PENDING',   NULL),
('ALEC002','T2-201','M04','Possession',            NULL,         672000.00, 60480.00, 60480.00, 0.00,      0.00,     0.00,     0.00, 0.00, 'PENDING',   NULL)
ON CONFLICT (customer_id, unit_number, milestone_code) DO UPDATE SET status = EXCLUDED.status;

-- ── RE Milestones — ALEC003 / PC-1102 ───────────────────────────────────────────
INSERT INTO re_milestones (customer_id, unit_number, milestone_code, description, billing_doc_no, basic_amt, cgst_amt, sgst_amt, tds_amt, basic_collected, cgst_collected, sgst_collected, tds_collected, status, billing_date) VALUES
('ALEC003','PC-1102','M01','Booking Amount',       '9000030001', 165000.00, 14850.00, 14850.00, 0.00, 165000.00, 14850.00, 14850.00, 0.00, 'COLLECTED', '2024-06-25'),
('ALEC003','PC-1102','M02','Foundation',           '9000030002', 550000.00, 49500.00, 49500.00, 0.00, 550000.00, 49500.00, 49500.00, 0.00, 'COLLECTED', '2024-09-30'),
('ALEC003','PC-1102','M03','Plinth Level',         '9000030003', 550000.00, 49500.00, 49500.00, 0.00,      0.00,     0.00,     0.00, 0.00, 'PENDING',   '2025-02-01'),
('ALEC003','PC-1102','M04','Possession',           NULL,         935000.00, 84150.00, 84150.00, 0.00,      0.00,     0.00,     0.00, 0.00, 'PENDING',   NULL)
ON CONFLICT (customer_id, unit_number, milestone_code) DO UPDATE SET status = EXCLUDED.status;

-- ── Customer Receipts — Demo pre-parked entry ────────────────────────────────────
INSERT INTO customer_receipts (park_ref, customer_id, unit_number, payment_mode, amount, instrument_ref, instrument_date, bank_name, excess_basic, excess_tds, status) VALUES
('PRK00000001', 'ALEC001', 'T1-304', 'Cheque', 500000.00, 'CH890123', '2026-03-15', 'HDFC Bank', 0.00, 0.00, 'PARKED')
ON CONFLICT (park_ref) DO NOTHING;

INSERT INTO receipt_allocations (park_ref, milestone_code, billing_doc_no, basic_applied, cgst_applied, sgst_applied, tds_applied) VALUES
('PRK00000001', 'M03', '9000010003', 350000.00, 43000.00, 43000.00, 0.00),
('PRK00000001', 'M04', '9000010004',  64000.00,     0.00,     0.00, 0.00)
ON CONFLICT DO NOTHING;

-- ── RE Brokers ───────────────────────────────────────────────────────────────────
INSERT INTO re_brokers (broker_id, name, pan, gstin, phone, payout_pct, bank_account, bank_name, status) VALUES
('BR001', 'Aakash Properties',    'BRKAP1234E', '24BRKAP1234E1ZK', '9898989898', 1.50, '50100012345678', 'HDFC Bank',  'ACTIVE'),
('BR002', 'Sunrise Realty',       'BRKSR5678F', NULL,               '9797979797', 1.25, '60200098765432', 'ICICI Bank', 'ACTIVE')
ON CONFLICT (broker_id) DO UPDATE SET name = EXCLUDED.name;

-- ── RE Broker Bookings ───────────────────────────────────────────────────────────
INSERT INTO re_broker_bookings (broker_id, customer_id, unit_number, sale_value, payout_amount, collected_pct, po_number, po_status, miro_status, tagged_date) VALUES
('BR001', 'ALEC001', 'T1-304', 6500000.00, 97500.00,  72.31, NULL, 'NOT_CREATED', 'PENDING', '2024-04-10'),
('BR001', 'ALEC002', 'T2-201', 4800000.00, 72000.00,  15.00, NULL, 'NOT_CREATED', 'PENDING', '2024-05-18'),
('BR002', 'ALEC003', 'PC-1102',5500000.00, 68750.00,  63.64, NULL, 'NOT_CREATED', 'PENDING', '2024-06-25')
ON CONFLICT DO NOTHING;
