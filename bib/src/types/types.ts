export type BaseCite = {
    name: string;
    author?: string;
    title: string;
    lang: 'english';
    url?: string;
    urldate?: string | Date;
};

export type OnlineCite = {
    type: 'online';
    url: string;
    citeDate: string | Date;
    date: string | Date;
} & BaseCite;

export type BookCite = {
    type: 'book';
    year: string;
    publisher: string;
    isbn?: string;
} & BaseCite;

export type ArticleCite = {
    type: 'article';
    journal: string;
    year: string;
    volume?: string;
    number?: string;
    pages?: string;
} & BaseCite;

export type ManualCite = {
    type: 'manual';
    organization: string;
    year: string;
    edition?: string;
    note?: string;
} & BaseCite;

export type Cite = OnlineCite | BookCite | ArticleCite | ManualCite;
