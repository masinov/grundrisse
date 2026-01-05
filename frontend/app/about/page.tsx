export default function AboutPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-gray-900 mb-8">About Grundrisse</h1>

      <div className="prose prose-gray max-w-none">
        <p className="text-lg text-gray-600 mb-6">
          Grundrisse is a digital archive and research platform for Marxist texts, combining
          comprehensive corpus access with AI-powered knowledge extraction.
        </p>

        <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-4">The Corpus</h2>
        <p className="text-gray-600 mb-4">
          Our archive contains over 19,000 works from the Marxist intellectual tradition,
          sourced from marxists.org. The corpus spans from the early writings of Marx and
          Engels through to contemporary Marxist thought, covering multiple languages and
          traditions.
        </p>

        <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-4">AI-Powered Extraction</h2>
        <p className="text-gray-600 mb-4">
          We use large language models to extract structured knowledge from the texts:
        </p>
        <ul className="list-disc list-inside text-gray-600 mb-4 space-y-2">
          <li>
            <strong>Concepts:</strong> Key terms and ideas mentioned in the text
          </li>
          <li>
            <strong>Claims:</strong> Assertions and arguments made by the authors
          </li>
          <li>
            <strong>Relationships:</strong> Connections between concepts across works (coming soon)
          </li>
        </ul>
        <p className="text-gray-600 mb-4">
          This extraction process is ongoing. Currently, a small number of works have been
          processed, with more being added regularly.
        </p>

        <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-4">Goals</h2>
        <p className="text-gray-600 mb-4">
          Our goal is to make the intellectual history of Marxism navigable and searchable,
          enabling scholars to:
        </p>
        <ul className="list-disc list-inside text-gray-600 mb-4 space-y-2">
          <li>Trace the development of concepts across authors and time periods</li>
          <li>Discover connections between texts and ideas</li>
          <li>Research specific topics with AI-assisted search</li>
          <li>Build on a shared, open knowledge base</li>
        </ul>

        <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-4">Open Source</h2>
        <p className="text-gray-600 mb-4">
          Grundrisse is an open source project. The code is available on GitHub, and we
          welcome contributions from developers, scholars, and anyone interested in
          making Marxist texts more accessible.
        </p>

        <h2 className="text-xl font-semibold text-gray-900 mt-8 mb-4">Contact</h2>
        <p className="text-gray-600 mb-4">
          For questions, suggestions, or collaboration inquiries, please open an issue on
          our GitHub repository.
        </p>
      </div>
    </div>
  );
}
