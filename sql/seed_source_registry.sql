-- Register existing sources without assigning categories or weights.
-- Existing registry entries are preserved.
-- Test locally before applying to shared Supabase.



INSERT INTO public.source_registry (source_normalized, name)
VALUES
    ('ai business', 'AI Business'),
    ('ars technica', 'Ars Technica'),
    ('bleepingcomputer', 'BleepingComputer'),
    ('breakit', 'Breakit'),
    ('computer weekly', 'Computer Weekly'),
    ('dark reading', 'Dark Reading'),
    ('engadget', 'Engadget'),
    ('forskning.se', 'Forskning.se'),
    ('geekwire', 'GeekWire'),
    ('github blog', 'GitHub Blog'),
    ('help net security', 'Help Net Security'),
    ('infoq', 'InfoQ'),
    ('krebs on security', 'Krebs on Security'),
    ('mit technology review', 'MIT Technology Review'),
    ('n8n blog', 'n8n Blog'),
    ('schneier on security', 'Schneier on Security'),
    ('sciencedaily ai', 'ScienceDaily AI'),
    ('sd times', 'SD Times'),
    ('securityweek', 'SecurityWeek'),
    ('siliconangle', 'SiliconANGLE'),
    ('sweclockers', 'SweClockers'),
    ('tech xplore', 'Tech Xplore'),
    ('tech.eu', 'Tech.eu'),
    ('techcrunch', 'TechCrunch'),
    ('techrepublic', 'TechRepublic'),
    ('the hacker news', 'The Hacker News'),
    ('the new stack', 'The New Stack'),
    ('the register', 'The Register'),
    ('unite.ai', 'Unite.AI'),
    ('wired', 'WIRED')
ON CONFLICT (source_normalized) DO NOTHING;
