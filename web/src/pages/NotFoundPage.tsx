import { Link } from "react-router";

import { PageTitle } from "./PageTitle";

export function NotFoundPage() {
  return (
    <section>
      <PageTitle>הדף לא נמצא</PageTitle>
      <Link to="/" className="text-accent underline">
        חזרה לתור האישורים
      </Link>
    </section>
  );
}
