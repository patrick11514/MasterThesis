import { Cite } from '$/types/types';

export const gen = (citations: Cite[]): string => {
    let final: string[] = [];

    for (const cite of citations) {
        let line = `@${cite.type}{${cite.name},\n`;

        if (cite.author) {
            line += `    author          = {${cite.author}},\n`;
        }

        line += `    title           = {${cite.title.replaceAll('&', '\\&')}},\n`;
        line += `    langid          = {${cite.lang}},\n`;

        if (cite.lang === 'english') {
            line += `    langidopts      = {variant=american},\n`;
        }

        switch (cite.type) {
            case 'online':
                line += `    date            = {${cite.date}},\n`;
                line += `    urldate         = {${cite.citeDate}},\n`;
                line += `    url             = {${cite.url}},\n`;
                break;

            case 'book':
                line += `    publisher       = {${cite.publisher}},\n`;
                if (cite.isbn) {
                    line += `    isbn            = {${cite.isbn}},\n`;
                }
                line += `    year            = {${cite.year}},\n`;
                break;

            case 'article':
                line += `    journal         = {${cite.journal}},\n`;
                line += `    year            = {${cite.year}},\n`;
                if (cite.volume) {
                    line += `    volume          = {${cite.volume}},\n`;
                }
                if (cite.number) {
                    line += `    number          = {${cite.number}},\n`;
                }
                if (cite.pages) {
                    line += `    pages           = {${cite.pages}},\n`;
                }
                break;

            case 'manual':
                line += `    organization    = {${cite.organization}},\n`;
                line += `    year            = {${cite.year}},\n`;
                if (cite.edition) {
                    line += `    edition         = {${cite.edition}},\n`;
                }
                if (cite.note) {
                    line += `    note            = {${cite.note}},\n`;
                }
                break;
        }

        if (cite.url) {
            line += `    url             = {${cite.url}},\n`;
        }

        if (cite.urldate) {
            line += `    urldate         = {${cite.urldate}},\n`;
        }

        line += `}\n`;
        final.push(line);
    }

    return final.join('\n');
};
