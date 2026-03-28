"""Public Terms of Service page at /terms."""
from __future__ import annotations

from .legal_document_page import build_legal_document_html

_TERMS_ARTICLE = """
<article class="legal-doc">
  <h1>Terms of Service</h1>
  <p class="legal-updated">Last updated: March 26, 2026</p>

  <p class="legal-lead">Welcome to Cartozo AI. By accessing or using our service, you agree to these Terms of Service.</p>

  <section id="tos-1" aria-labelledby="tos-h1">
    <h2 id="tos-h1">1. Introduction</h2>
    <p>Cartozo AI (&quot;we&quot;, &quot;our&quot;, &quot;us&quot;) provides a SaaS platform for product feed optimization and search-intent positioning for listings (e.g. Google Merchant) using artificial intelligence.</p>
    <p>By using Cartozo AI, you agree to comply with and be bound by these Terms. If you do not agree, do not use the service.</p>
  </section>

  <section id="tos-2" aria-labelledby="tos-h2">
    <h2 id="tos-h2">2. Use of the Service</h2>
    <p>You may use Cartozo AI only in accordance with these Terms and applicable laws.</p>
    <p>You agree <strong>not</strong> to:</p>
    <ul>
      <li>Use the service for illegal or unauthorized purposes</li>
      <li>Upload harmful, misleading, or fraudulent content</li>
      <li>Attempt to reverse engineer, copy, or exploit the system</li>
      <li>Abuse APIs or overload the platform</li>
      <li>Use the service to violate third-party platform policies (e.g., Google Merchant)</li>
    </ul>
    <p>We reserve the right to suspend or terminate access if misuse is detected.</p>
  </section>

  <section id="tos-3" aria-labelledby="tos-h3">
    <h2 id="tos-h3">3. Accounts</h2>
    <p>To use certain features, you must create an account.</p>
    <p>You are responsible for:</p>
    <ul>
      <li>Keeping your credentials secure</li>
      <li>All activity under your account</li>
    </ul>
    <p>We may suspend or terminate accounts that:</p>
    <ul>
      <li>Violate these Terms</li>
      <li>Show suspicious or abusive behavior</li>
    </ul>
  </section>

  <section id="tos-4" aria-labelledby="tos-h4">
    <h2 id="tos-h4">4. Payments and Subscriptions</h2>
    <p>Cartozo AI operates on a subscription basis.</p>
    <ul>
      <li>Plans are billed monthly</li>
      <li>Subscriptions renew automatically unless canceled</li>
      <li>Prices may change at any time with notice</li>
    </ul>
    <p><strong>Refunds:</strong> Payments are generally non-refundable unless required by law or granted at our discretion.</p>
  </section>

  <section id="tos-5" aria-labelledby="tos-h5">
    <h2 id="tos-h5">5. AI Disclaimer</h2>
    <p>Cartozo AI uses artificial intelligence to generate and optimize content.</p>
    <p>You acknowledge that:</p>
    <ul>
      <li>AI-generated results may be inaccurate, incomplete, or unsuitable</li>
      <li>You are responsible for reviewing and approving all outputs before use</li>
      <li>We do not guarantee performance improvements (e.g., SEO rankings, ad results, conversions)</li>
    </ul>
    <p>Use of AI outputs is at your own risk.</p>
  </section>

  <section id="tos-6" aria-labelledby="tos-h6">
    <h2 id="tos-h6">6. User Data and Content</h2>
    <p>You retain ownership of all data you upload, including product feeds.</p>
    <p>By using the service, you grant us a limited right to:</p>
    <ul>
      <li>Process your data to provide the service</li>
      <li>Improve system performance and AI models (in aggregated or anonymized form)</li>
    </ul>
    <p>We do not claim ownership over your content.</p>
  </section>

  <section id="tos-7" aria-labelledby="tos-h7">
    <h2 id="tos-h7">7. Third-Party Integrations</h2>
    <p>Cartozo AI may integrate with third-party platforms such as Google Merchant Center.</p>
    <p>We are not responsible for:</p>
    <ul>
      <li>Product disapprovals</li>
      <li>Account suspensions</li>
      <li>Policy violations on third-party platforms</li>
    </ul>
    <p>You are solely responsible for ensuring compliance with external platform rules.</p>
  </section>

  <section id="tos-8" aria-labelledby="tos-h8">
    <h2 id="tos-h8">8. Intellectual Property</h2>
    <p>All rights to the Cartozo AI platform, including:</p>
    <ul>
      <li>Software</li>
      <li>Design</li>
      <li>Branding</li>
    </ul>
    <p>remain the property of Cartozo AI.</p>
    <p>You may not copy, distribute, or recreate any part of the service without permission.</p>
    <p>Generated outputs belong to you, subject to applicable laws.</p>
  </section>

  <section id="tos-9" aria-labelledby="tos-h9">
    <h2 id="tos-h9">9. Limitation of Liability</h2>
    <p>To the maximum extent permitted by law, Cartozo AI is not liable for:</p>
    <ul>
      <li>Loss of profits, revenue, or data</li>
      <li>Business interruptions</li>
      <li>Third-party platform penalties (e.g., Google account issues)</li>
      <li>Any indirect or consequential damages</li>
    </ul>
    <p>The service is provided &quot;as is&quot; without warranties of any kind.</p>
  </section>

  <section id="tos-10" aria-labelledby="tos-h10">
    <h2 id="tos-h10">10. Termination</h2>
    <p>We may suspend or terminate your access at any time if:</p>
    <ul>
      <li>You violate these Terms</li>
      <li>You misuse the platform</li>
    </ul>
    <p>You may stop using the service at any time.</p>
  </section>

  <section id="tos-11" aria-labelledby="tos-h11">
    <h2 id="tos-h11">11. Changes to Terms</h2>
    <p>We may update these Terms from time to time.</p>
    <p>Changes will be posted on this page with an updated date. Continued use of the service means you accept the changes.</p>
  </section>

  <section id="tos-12" aria-labelledby="tos-h12">
    <h2 id="tos-h12">12. Governing Law</h2>
    <p>These Terms are governed by applicable laws in relevant jurisdictions, depending on your location.</p>
  </section>

  <section id="tos-13" aria-labelledby="tos-h13">
    <h2 id="tos-h13">13. Contact</h2>
    <p>If you have any questions about these Terms, contact us at:</p>
    <p>Email: <a href="mailto:support@cartozo.ai">support@cartozo.ai</a></p>
  </section>
</article>
"""


def build_terms_html(
    *,
    meta_title: str,
    meta_description: str,
    og_title: str,
    og_description: str,
    canonical_url: str,
    og_image: str = "",
    gtm_head: str,
    gtm_body: str,
) -> str:
    return build_legal_document_html(
        article_html=_TERMS_ARTICLE,
        meta_title=meta_title,
        meta_description=meta_description,
        og_title=og_title,
        og_description=og_description,
        canonical_url=canonical_url,
        og_image=og_image,
        gtm_head=gtm_head,
        gtm_body=gtm_body,
    )
