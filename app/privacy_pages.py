"""Privacy Policy and Cookie Policy public pages."""
from __future__ import annotations

from .legal_document_page import build_legal_document_html

_PRIVACY_ARTICLE = """
<article class="legal-doc">
  <h1>Privacy Policy</h1>
  <p class="legal-updated">Last updated: March 27, 2026</p>

  <p class="legal-lead">This Privacy Policy explains how Cartozo AI (&quot;we&quot;, &quot;our&quot;, &quot;us&quot;) collects, uses, and protects information when you use our website and services.</p>

  <section id="pp-1" aria-labelledby="pp-h1">
    <h2 id="pp-h1">1. Who we are</h2>
    <p>Cartozo AI provides a cloud service for product feed quality and search-intent positioning (titles, descriptions, and related e-commerce content). For privacy questions, contact us at <a href="mailto:support@cartozo.ai">support@cartozo.ai</a>.</p>
  </section>

  <section id="pp-2" aria-labelledby="pp-h2">
    <h2 id="pp-h2">2. Information we collect</h2>
    <p>We may collect:</p>
    <ul>
      <li><strong>Account data:</strong> such as name, email address, and authentication identifiers when you sign in (e.g., via Google).</li>
      <li><strong>Content you upload:</strong> including product feeds (CSV), mappings, and related files you submit for processing.</li>
      <li><strong>Usage and technical data:</strong> such as IP address, browser type, device information, pages visited, and approximate location derived from IP.</li>
      <li><strong>Communications:</strong> messages you send us (e.g., contact form, support email).</li>
    </ul>
  </section>

  <section id="pp-3" aria-labelledby="pp-h3">
    <h2 id="pp-h3">3. How we use information</h2>
    <p>We use the information above to:</p>
    <ul>
      <li>Provide, operate, and improve the service</li>
      <li>Authenticate users and secure accounts</li>
      <li>Process your uploads and return optimized results</li>
      <li>Communicate with you about the service</li>
      <li>Comply with legal obligations and enforce our <a href="/terms">Terms of Service</a></li>
    </ul>
  </section>

  <section id="pp-4" aria-labelledby="pp-h4">
    <h2 id="pp-h4">4. Legal bases (where applicable)</h2>
    <p>Depending on your region, we may rely on contractual necessity, legitimate interests (e.g., security and product improvement), consent (where required), or legal obligation.</p>
  </section>

  <section id="pp-5" aria-labelledby="pp-h5">
    <h2 id="pp-h5">5. Cookies and similar technologies</h2>
    <p>We use cookies and similar technologies as described in our <a href="/cookies">Cookie Policy</a>. You can manage preferences through your browser and, where available, our cookie controls.</p>
  </section>

  <section id="pp-6" aria-labelledby="pp-h6">
    <h2 id="pp-h6">6. Sharing of information</h2>
    <p>We may share information with:</p>
    <ul>
      <li><strong>Service providers</strong> who assist us (e.g., hosting, analytics, email) under appropriate agreements</li>
      <li><strong>Integrations you enable</strong> (e.g., Google APIs) according to your use of those features</li>
      <li><strong>Authorities</strong> when required by law or to protect rights and safety</li>
    </ul>
    <p>We do not sell your personal information as a conventional &quot;sale&quot; of data.</p>
  </section>

  <section id="pp-7" aria-labelledby="pp-h7">
    <h2 id="pp-h7">7. Retention</h2>
    <p>We retain information only as long as needed for the purposes above, unless a longer period is required by law. Uploads and batch data may be deleted or anonymized according to our operational policies and your account status.</p>
  </section>

  <section id="pp-8" aria-labelledby="pp-h8">
    <h2 id="pp-h8">8. Security</h2>
    <p>We implement appropriate technical and organizational measures to protect information. No method of transmission over the Internet is 100% secure.</p>
  </section>

  <section id="pp-9" aria-labelledby="pp-h9">
    <h2 id="pp-h9">9. International transfers</h2>
    <p>If we transfer data across borders, we take steps consistent with applicable law (e.g., appropriate safeguards or your consent where required).</p>
  </section>

  <section id="pp-10" aria-labelledby="pp-h10">
    <h2 id="pp-h10">10. Your rights</h2>
    <p>Depending on where you live, you may have rights to access, correct, delete, or export your personal data, or to object to or restrict certain processing. To exercise these rights, contact <a href="mailto:support@cartozo.ai">support@cartozo.ai</a>.</p>
  </section>

  <section id="pp-11" aria-labelledby="pp-h11">
    <h2 id="pp-h11">11. Children</h2>
    <p>The service is not directed at children under 16 (or the age required in your jurisdiction). We do not knowingly collect personal information from children.</p>
  </section>

  <section id="pp-12" aria-labelledby="pp-h12">
    <h2 id="pp-h12">12. Changes</h2>
    <p>We may update this Privacy Policy from time to time. The &quot;Last updated&quot; date will change when we do. Continued use after changes means you accept the updated policy.</p>
  </section>
</article>
"""

_COOKIE_ARTICLE = """
<article class="legal-doc">
  <h1>Cookie Policy</h1>
  <p class="legal-updated">Last updated: March 27, 2026</p>

  <p class="legal-lead">This Cookie Policy explains how Cartozo AI uses cookies and similar technologies on cartozo.ai and related services.</p>

  <section id="ck-1" aria-labelledby="ck-h1">
    <h2 id="ck-h1">1. What are cookies?</h2>
    <p>Cookies are small text files stored on your device when you visit a site. Similar technologies include local storage and pixels. They help the site function, remember preferences, and understand usage.</p>
  </section>

  <section id="ck-2" aria-labelledby="ck-h2">
    <h2 id="ck-h2">2. How we use cookies</h2>
    <p>We use cookies and similar technologies for purposes such as:</p>
    <ul>
      <li><strong>Essential / functional:</strong> keeping you signed in, security, load balancing, and remembering theme or session choices</li>
      <li><strong>Analytics / measurement:</strong> understanding how visitors use the site (e.g., via Google Tag Manager / GA4 where configured)</li>
      <li><strong>Marketing (if enabled):</strong> measuring campaign effectiveness; only where allowed by your settings and applicable law</li>
    </ul>
  </section>

  <section id="ck-3" aria-labelledby="ck-h3">
    <h2 id="ck-h3">3. Third-party cookies</h2>
    <p>Some cookies are set by third parties (e.g., Google for authentication or analytics). Those providers have their own privacy notices. We encourage you to review them.</p>
  </section>

  <section id="ck-4" aria-labelledby="ck-h4">
    <h2 id="ck-h4">4. Managing cookies</h2>
    <p>You can control cookies through your browser settings (block, delete, or alert). Blocking essential cookies may affect sign-in or site functionality. For analytics, you may also use opt-out tools provided by vendors where available.</p>
  </section>

  <section id="ck-5" aria-labelledby="ck-h5">
    <h2 id="ck-h5">5. Updates</h2>
    <p>We may update this Cookie Policy when our practices change. Check the &quot;Last updated&quot; date above.</p>
  </section>

  <section id="ck-6" aria-labelledby="ck-h6">
    <h2 id="ck-h6">6. More information</h2>
    <p>For how we handle personal data, see our <a href="/privacy">Privacy Policy</a> and <a href="/terms">Terms of Service</a>. Questions: <a href="mailto:support@cartozo.ai">support@cartozo.ai</a>.</p>
  </section>
</article>
"""


def build_privacy_policy_html(
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
        article_html=_PRIVACY_ARTICLE,
        meta_title=meta_title,
        meta_description=meta_description,
        og_title=og_title,
        og_description=og_description,
        canonical_url=canonical_url,
        og_image=og_image,
        gtm_head=gtm_head,
        gtm_body=gtm_body,
    )


def build_cookie_policy_html(
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
        article_html=_COOKIE_ARTICLE,
        meta_title=meta_title,
        meta_description=meta_description,
        og_title=og_title,
        og_description=og_description,
        canonical_url=canonical_url,
        og_image=og_image,
        gtm_head=gtm_head,
        gtm_body=gtm_body,
    )


_REFUND_ARTICLE = """
<article class="legal-doc">
  <h1>Refund Policy</h1>
  <p class="legal-updated">Last updated: March 27, 2026</p>

  <p class="legal-lead">This Refund Policy explains how refunds may apply to Cartozo AI subscriptions and paid add-ons. It supplements our <a href="/terms">Terms of Service</a>.</p>

  <section id="rf-1" aria-labelledby="rf-h1">
    <h2 id="rf-h1">1. Billing and payment processors</h2>
    <p>Payments may be processed by third parties (e.g., Paddle, PayPro, or other providers shown at checkout). Their terms and dispute windows may apply in addition to this policy.</p>
  </section>

  <section id="rf-2" aria-labelledby="rf-h2">
    <h2 id="rf-h2">2. Subscription refunds</h2>
    <p>If you believe a charge was made in error or you are eligible for a refund under applicable law or the payment provider&apos;s rules, contact <a href="mailto:support@cartozo.ai">support@cartozo.ai</a> with your account email, invoice or transaction ID, and a short description. We review requests in good faith and coordinate with the processor where applicable.</p>
  </section>

  <section id="rf-3" aria-labelledby="rf-h3">
    <h2 id="rf-h3">3. No guarantee of refunds</h2>
    <p>Except where required by law, refunds are not guaranteed. Eligibility may depend on time since purchase, usage of the service, promotional terms, and processor policies.</p>
  </section>

  <section id="rf-4" aria-labelledby="rf-h4">
    <h2 id="rf-h4">4. Chargebacks</h2>
    <p>Please contact us before initiating a chargeback so we can help resolve the issue. Unwarranted chargebacks may affect account access.</p>
  </section>

  <section id="rf-5" aria-labelledby="rf-h5">
    <h2 id="rf-h5">5. Changes</h2>
    <p>We may update this policy from time to time. The &quot;Last updated&quot; date reflects the latest version.</p>
  </section>
</article>
"""


def build_refund_policy_html(
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
        article_html=_REFUND_ARTICLE,
        meta_title=meta_title,
        meta_description=meta_description,
        og_title=og_title,
        og_description=og_description,
        canonical_url=canonical_url,
        og_image=og_image,
        gtm_head=gtm_head,
        gtm_body=gtm_body,
    )
