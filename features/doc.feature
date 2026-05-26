Feature: Visio document factory + open / save round-trip
  In order to satisfy myself that python-vsdx can read and write
  As a vsdx developer
  I want to see the top-level Visio() / VisioDocument.save factories
  pass a basic round-trip sanity check

  Scenario: Open a fresh blank document
     When I create a new document with vsdx.Visio()
     Then the document has zero pages
      And the document exposes a Pages collection
      And the document exposes a Masters collection

  Scenario: Add a page to a fresh document
     When I create a new document with vsdx.Visio()
      And I call doc.pages.add_page()
     Then the document has one page

  Scenario: Round-trip a fresh document via a BytesIO buffer
     When I create a new document with vsdx.Visio()
      And I save the document to an io.BytesIO
     Then the buffer contains a ZIP starting with PK
      And I can re-open the saved bytes as a Visio document

  Scenario: Round-trip a fresh document via a filesystem path
     When I create a new document with vsdx.Visio()
      And I save the document to a temporary path
     Then the file exists on disk
      And the file opens cleanly with vsdx.Visio()

  Scenario: Open the bundled default template
     Given the bundled default.vsdx template
     When I open the template with vsdx.Visio()
     Then the document carries a non-None theme

  Scenario: Round-trip the bundled default template through a buffer
     Given the bundled default.vsdx template
     When I open the template with vsdx.Visio()
      And I save the document to an io.BytesIO
     Then the buffer contains a ZIP starting with PK
      And I can re-open the saved bytes as a Visio document

  Scenario: Visio() rejects a stencil source
     Given a freshly-saved stencil at a temporary path
     Then opening it with vsdx.Visio() raises ValueError

  Scenario: Stencil() rejects a drawing source
     Given a freshly-saved drawing at a temporary path
     Then opening it with vsdx.Stencil() raises ValueError
