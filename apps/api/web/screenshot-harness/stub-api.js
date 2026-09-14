export const api = {
  getQueryConstraints: async () => ({
    category: ['Skincare','Makeup','Fragrance','Haircare','Cross-Category','Grooming','Oral Care','Baby Care','General'],
    stage: ['Awareness','Research','Comparison','Ready to Buy'],
    specificity: ['Broad','Mid','Narrow'],
    persona: ['Casual / Gift Buyer','Value-Conscious','Beauty Enthusiast','New / First-Time Parent','Value-Conscious Parent'],
    status: ['Active','Paused','Retired'],
    study_pattern: ['retailer','brand_at_retail','brand_vs_brand'],
  }),
  getEntities: async () => ([
    { id: 1, name: 'Amazon', category: 'marketplace' },
    { id: 2, name: 'Target', category: 'mass' },
  ]),
  generateStudy: async () => ({ study_type: 'demo' }),
}
