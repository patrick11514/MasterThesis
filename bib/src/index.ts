import fs from 'node:fs';
import { gen } from './lib/gen';
import { prompt } from './lib/prompt';
import { BaseCite, Cite } from './types/types';

const types: Cite['type'][] = ['online', 'book', 'article', 'manual'];

const toYYYYMMDD = (date: Date): string => {
    return date.toISOString().split('T')[0];
};

const SOURCE_FILE = 'src.json';

const ensureSourceFile = (): void => {
    if (!fs.existsSync(SOURCE_FILE)) {
        fs.writeFileSync(SOURCE_FILE, '[]\n');
    }
};

const readCites = (): Cite[] => {
    ensureSourceFile();
    const raw = fs.readFileSync(SOURCE_FILE, 'utf-8').trim();

    if (raw === '') {
        return [];
    }

    return JSON.parse(raw) as Cite[];
};

if (process.argv.includes('--generate')) {
    const cites = readCites();
    fs.writeFileSync('sources.bib', gen(cites));
    process.exit(0);
} else if (process.argv.includes('--add')) {
    console.log('Select type of source: ');
    for (let i = 0; i < types.length; i++) {
        console.log(`${i + 1}. ${types[i]}`);
    }

    const { type, name, title, author, lang } = await prompt([
        {
            type: 'select',
            name: 'type',
            message: 'Select type of source: ',
            choices: types
        },
        { type: 'input', name: 'name', message: 'Enter the name of the source: ' },
        {
            type: 'input',
            name: 'title',
            message: 'Enter the title of the source: '
        },
        {
            type: 'input',
            name: 'author',
            message: 'Enter the author of the source: (optional)',
            initial: ''
        },
        {
            type: 'select',
            name: 'lang',
            message: 'Enter the language of the source: ',
            choices: ['english'] satisfies Cite['lang'][]
        }
    ] as const);

    const baseCite = {
        name,
        title,
        author: author === '' ? undefined : author,
        lang
    } satisfies BaseCite;

    let cite: Cite;
    switch (type) {
        case 'online': {
            const { date, citeDate, url } = await prompt([
                {
                    type: 'input',
                    name: 'date',
                    message: 'Enter the date of the source: ',
                    initial: toYYYYMMDD(new Date())
                },
                {
                    type: 'input',
                    name: 'citeDate',
                    message: 'Enter the date you cited the source: ',
                    initial: toYYYYMMDD(new Date())
                },
                {
                    type: 'input',
                    name: 'url',
                    message: 'Enter the URL of the source: '
                }
            ] as const);

            cite = {
                type,
                date,
                citeDate,
                url,
                ...baseCite
            } satisfies Cite;
            break;
        }
        case 'book': {
            const {
                year: bookYear,
                publisher,
                isbn
            } = await prompt([
                {
                    type: 'input',
                    name: 'year',
                    message: 'Enter the year of the source: '
                },
                {
                    type: 'input',
                    name: 'publisher',
                    message: 'Enter the publisher: '
                },
                {
                    type: 'input',
                    name: 'isbn',
                    message: 'Enter the ISBN (optional): ',
                    initial: ''
                }
            ] as const);
            cite = {
                type,
                year: bookYear,
                publisher,
                isbn: isbn === '' ? undefined : isbn,
                ...baseCite
            } satisfies Cite;
            break;
        }
        case 'article': {
            const {
                journal,
                year: articleYear,
                volume,
                number,
                pages
            } = await prompt([
                {
                    type: 'input',
                    name: 'journal',
                    message: 'Enter the journal name: '
                },
                {
                    type: 'input',
                    name: 'year',
                    message: 'Enter the year of the source: '
                },
                {
                    type: 'input',
                    name: 'volume',
                    message: 'Enter the volume (optional): ',
                    initial: ''
                },
                {
                    type: 'input',
                    name: 'number',
                    message: 'Enter the number (optional): ',
                    initial: ''
                },
                {
                    type: 'input',
                    name: 'pages',
                    message: 'Enter pages (optional): ',
                    initial: ''
                }
            ] as const);
            cite = {
                type,
                journal,
                year: articleYear,
                volume: volume === '' ? undefined : volume,
                number: number === '' ? undefined : number,
                pages: pages === '' ? undefined : pages,
                ...baseCite
            } satisfies Cite;
            break;
        }
        case 'manual': {
            const {
                organization,
                year: manualYear,
                edition,
                note,
                url,
                urldate
            } = await prompt([
                {
                    type: 'input',
                    name: 'organization',
                    message: 'Enter the organization: '
                },
                {
                    type: 'input',
                    name: 'year',
                    message: 'Enter the year of the source: '
                },
                {
                    type: 'input',
                    name: 'edition',
                    message: 'Enter the edition (optional): ',
                    initial: ''
                },
                {
                    type: 'input',
                    name: 'note',
                    message: 'Enter a note (optional): ',
                    initial: ''
                },
                {
                    type: 'input',
                    name: 'url',
                    message: 'Enter the URL (optional): ',
                    initial: ''
                },
                {
                    type: 'input',
                    name: 'urldate',
                    message: 'Enter URL access date (optional): ',
                    initial: toYYYYMMDD(new Date())
                }
            ] as const);
            cite = {
                type,
                organization,
                year: manualYear,
                edition: edition === '' ? undefined : edition,
                note: note === '' ? undefined : note,
                url: url === '' ? undefined : url,
                urldate: urldate === '' ? undefined : urldate,
                ...baseCite
            } satisfies Cite;
            break;
        }
    }

    const cites = readCites();
    cites.push(cite);

    fs.writeFileSync(SOURCE_FILE, JSON.stringify(cites, null, 4));

    console.log('Source added successfully!');
}
